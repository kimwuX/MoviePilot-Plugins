from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class MTorrent(_ISiteSigninHandler):
    """
    m-team签到
    """

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return ["api.m-team.cc", "api.m-team.io"]

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        logger.warning(f"{site} 签到失败，无签到功能")
        return False, '签到失败，无签到功能'

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        #site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")
        token = site_info.get("token")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        signin_url = urljoin(url, "/api/member/updateLastBrowse")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Authorization": token
        }
        # domain = StringUtils.get_url_domain(url)
        # 更新最后访问时间
        res = RequestUtils(headers=headers,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout,
                           referer=urljoin(url, "/index")
                           ).post_res(url=signin_url)
        if res:
            return True, "模拟登录成功"
        elif res is not None:
            return False, f"模拟登录失败，状态码：{res.status_code}"
        else:
            return False, "模拟登录失败，无法打开网站"
