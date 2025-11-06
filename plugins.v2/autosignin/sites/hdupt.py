import re
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class HDUPT(_ISiteSigninHandler):
    """
    hdu签到
    """

    # 已签到
    _sign_regex = ['<span id="yiqiandao">']

    # 签到成功
    _success_text = '本次签到获得魅力'

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "pt.hdupt.com"

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
        signin_url = urljoin(url, "/added.php?action=qiandao")

        # 获取页面html
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

        # 签到
        html_text = self.get_page_source(url=signin_url,
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)
        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        logger.debug(f"{site} 签到接口返回 {html_text}")
        # 判断是否已签到 sign_res.text = ".23"
        if len(list(map(int, re.findall(r"\d+", html_text)))) > 0:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_text}")
        return False, '签到失败，请查看日志'
