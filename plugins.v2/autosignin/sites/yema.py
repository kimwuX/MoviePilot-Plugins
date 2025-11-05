from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class YemaPT(_ISiteSigninHandler):
    """
    YemaPT 签到
    """

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "yemapt.org"

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
        signin_url = urljoin(url, "/api/consumer/checkIn")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
        }
        # 获取用户信息，更新最后访问时间
        res = RequestUtils(headers=headers,
                           cookies=site_cookie,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout,
                           referer=url
                           ).get_res(signin_url)

        if res and res.json().get("success"):
            return True, "签到成功"
        elif res is not None:
            return False, f"签到失败，签到结果：{res.json().get('errorMessage')}"
        else:
            return False, "签到失败，无法打开网站"

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        login_url = urljoin(url, "/api/user/profile")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
        }
        # 获取用户信息，更新最后访问时间
        res = RequestUtils(headers=headers,
                           cookies=site_cookie,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout,
                           referer=url
                           ).get_res(login_url)

        if res and res.json().get("success"):
            return True, "模拟登录成功"
        elif res is not None:
            return False, f"模拟登录失败，状态码：{res.status_code}"
        else:
            return False, "模拟登录失败，无法打开网站"
