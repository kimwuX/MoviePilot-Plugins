import time
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class HDSky(_ISiteSigninHandler):
    """
    天空签到
    """

    # 已签到
    _sign_regex = ['已签到']

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return ["hdsky.me", "hdsky.my"]

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        ua = site_info.get("ua")
        cookies = site_info.get("cookie")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/showup.php")
        get_image_url = urljoin(url, "/image_code_ajax.php")

        # 判断今日是否已签到
        html_text = self.get_page_source(url=url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        if self.test_re(text=html_text, regexs=self._sign_regex):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 获取验证码请求，考虑到网络问题获取失败，多获取几次试试
        res_times = 0
        img_hash = None
        while res_times <= 3:
            if res_times > 0:
                time.sleep(1)
                logger.warning(f"{site} 验证码图片获取失败，正在进行第{res_times}次重试")
            html_image = self.post_res(url=get_image_url,
                                       ua=ua,
                                       cookies=cookies,
                                       proxy=proxy,
                                       timeout=timeout,
                                       referer=url,
                                       data={'action': 'new'})
            image_dict = self.safe_json_loads(html_image)
            if image_dict and image_dict.get("success"):
                img_hash = image_dict.get("code")
                break
            res_times += 1

        if not img_hash:
            logger.warning(f"{site} 签到失败，签到参数获取失败")
            return False, '签到失败，签到参数获取失败'

        # 完整验证码url
        img_url = urljoin(url, f'/image.php?action=regimage&imagehash={img_hash}')
        logger.debug(f"{site} 验证码链接：{img_url}")

        # 验证码识别
        ocr_result = self.img_ocr(site=site,
                                  image_url=img_url,
                                  cookie=cookies,
                                  ua=ua)
        if not ocr_result or len(ocr_result) != 6:
            logger.warning(f'{site} 签到失败，验证码识别失败')
            return False, '签到失败，验证码识别失败'

        # 组装请求参数
        data = {
            'action': 'showup',
            'imagehash': img_hash,
            'imagestring': ocr_result
        }
        logger.debug(f"{site} 签到请求参数：{data}")

        # 签到
        html_sign = self.post_res(url=signin_url,
                                  ua=ua,
                                  cookies=cookies,
                                  proxy=proxy,
                                  timeout=timeout,
                                  referer=url,
                                  data=data)

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = self.safe_json_loads(html_sign)
        if not sign_dict:
            logger.warning(f"{site} 签到失败，签到数据解析失败：\n{html_sign}")
            return False, '签到失败，签到数据解析失败'

        # {"success":true,"message":1030}
        if sign_dict.get("success"):
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        # {"success":false,"message":"date_unmatch"}
        if str(sign_dict.get("message")) == "date_unmatch":
            # 重复签到
            logger.warning(f"{site} 重复签到")
            return True, '今日已签到'

        # {"success":false,"message":"invalid_imagehash"}
        if str(sign_dict.get("message")) == "invalid_imagehash":
            # 验证码错误
            logger.warning(f"{site} 签到失败，验证码错误")
            return False, '签到失败，验证码错误'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_sign}")
        return False, '签到失败，请查看日志'
