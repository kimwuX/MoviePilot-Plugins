from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.helper.cloudflare import under_challenge
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class BTSchool(_ISiteSigninHandler):
    """
    学校签到
    """

    # 已签到
    _sign_text = '每日签到'

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "pt.btschool.club"

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
        signin_url = urljoin(url, "/index.php?action=addbonus")

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

        if under_challenge(html_text):
            logger.warning(f"{site} 签到失败，无法绕过Cloudflare检测")
            return False, '签到失败，无法绕过Cloudflare检测'

        # 已签到
        if self._sign_text not in html_text:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        html_text = self.get_page_source(url=signin_url,
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        if not html_text:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        if under_challenge(html_text):
            logger.warning(f"{site} 签到失败，无法绕过Cloudflare检测")
            return False, '签到失败，无法绕过Cloudflare检测'

        # 签到成功
        if self._sign_text not in html_text:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_text}")
        return False, '签到失败，请查看日志'
