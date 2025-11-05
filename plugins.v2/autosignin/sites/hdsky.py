import json
import time
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.helper.ocr import OcrHelper
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


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
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/showup.php")
        get_image_url = urljoin(url, "/image_code_ajax.php")

        # 判断今日是否已签到
        html_text = self.get_page_source(url=url,
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)
        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._sign_regex)
        if sign_status:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 获取验证码请求，考虑到网络问题获取失败，多获取几次试试
        res_times = 0
        img_hash = None
        while res_times <= 3:
            if res_times > 0:
                logger.warning(f"{site} 验证码图片获取失败，正在进行第{res_times}次重试")
            image_res = RequestUtils(cookies=site_cookie,
                                     ua=ua,
                                     proxies=settings.PROXY if proxy else None,
                                     timeout=timeout,
                                     referer=url,
                                     content_type='application/x-www-form-urlencoded; charset=UTF-8',
                                     accept_type="*/*"
                                     ).post_res(url=get_image_url,
                                                data={'action': 'new'})
            if image_res and image_res.status_code == 200:
                image_json = json.loads(image_res.text)
                if image_json["success"]:
                    img_hash = image_json["code"]
                    break
                res_times += 1
                time.sleep(1)

        if not img_hash:
            logger.warning(f"{site} 签到失败，获取签到参数失败")
            return False, '签到失败，获取签到参数失败'

        # 完整验证码url
        img_url = urljoin(url, f'/image.php?action=regimage&imagehash={img_hash}')
        logger.info(f"{site} 验证码链接：{img_url}")

        # ocr识别多次，获取6位验证码
        times = 0
        ocr_result = None
        # 识别几次
        while times <= 3:
            if times > 0:
                logger.warning(f"{site} 验证码识别失败，正在进行第{times}次重试")
            # ocr二维码识别
            ocr_result = OcrHelper().get_captcha_text(image_url=img_url,
                                                      cookie=site_cookie,
                                                      ua=ua)
            if ocr_result:
                if len(ocr_result) == 6:
                    logger.info(f"{site} 验证码识别成功：{ocr_result}")
                    break
                logger.warning(f"{site} 验证码识别错误：{ocr_result}")
            times += 1
            time.sleep(1)

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
        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout,
                                referer=url
                                ).post_res(url=signin_url, data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = json.loads(sign_res.text)
        if sign_dict["success"]:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'
        elif str(sign_dict["message"]) == "date_unmatch":
            # 重复签到
            logger.warning(f"{site} 重复签到")
            return True, '今日已签到'
        elif str(sign_dict["message"]) == "invalid_imagehash":
            # 验证码错误
            logger.warning(f"{site} 签到失败，验证码错误")
            return False, '签到失败，验证码错误'
        else:
            logger.warning(f"{site} 签到失败，接口返回：\n{sign_res.text}")
            return False, '签到失败，请查看日志'

