from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.string import StringUtils


class PTTime(_ISiteSigninHandler):
    """
    PT时间签到
    """

    # 已签到
    # 拒绝访问：已签到，无需再签
    _sign_regex = ['已签到，无需再签']
    # 签到成功
    _succeed_regex = ['签到成功']

    _signin_path = "/attendance.php"
    # 签到地址
    _signin_url = "https://www.pttime.org/attendance.php"

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "www.pttime.org"

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

        self._signin_url = urljoin(url, self._signin_path)
        logger.info(f"开始签到 {site}，地址：{self._signin_url}")

        # 签到
        # 签到返回：<html><head></head><body>签到成功</body></html>
        html_text = self.get_page_source(url=self._signin_url,
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

        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._succeed_regex)
        if sign_status:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_text}")
        return False, '签到失败，请查看日志'
