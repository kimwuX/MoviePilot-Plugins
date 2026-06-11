from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class LJD(_ISiteSigninHandler):
    """
    垃圾堆签到
    """

    # 签到成功
    # 这是您的第 <b>1</b> 次签到，已连续签到 <b>1</b> 天，本次签到获得 <b>10</b> 个魔力值。
    _success_regex = [r'连续签到\s*\S*?\d+\S*?\s*天，本次签到获得']

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "pt.lajidui.top"

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
        signin_url = urljoin(url, "/attendance.php")

        html_text = self.get_page_source(url=signin_url,
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

        # 已签到
        if self.test_re(text=html_text, regexs=self._success_regex):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_text)
        if not html:
            logger.warning(f"{site} 签到失败，无法解析：\n{html_text}")
            return False, f'签到失败，无法解析文档'

        # 签到参数
        img_capt = html.xpath('//img[@alt="CAPTCHA"]/@src')
        img_hash = html.xpath('//input[@name="imagehash"]/@value')
        if not img_capt or not img_hash:
            logger.warning(f"{site} 签到失败，获取签到参数失败")
            return False, '签到失败，获取签到参数失败'

        logger.debug(f"{site} img_capt: {img_capt}")
        logger.debug(f"{site} img_hash: {img_hash}")

        # 完整验证码url
        img_url = urljoin(url, img_capt[0])
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
            'imagehash': img_hash[0],
            'imagestring': ocr_result
        }
        logger.debug(f"{site} 签到请求参数：{data}")

        # 签到
        sign_res = RequestUtils(ua=ua,
                                cookies=cookies,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).post_res(url=signin_url, data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 判断是否签到成功
        if self.test_re(text=sign_res.text, regexs=self._success_regex):
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{sign_res.text}")
        return False, '签到失败，请查看日志'
