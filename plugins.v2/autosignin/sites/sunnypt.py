from typing import Tuple

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.string import StringUtils


class SunnyPT(_ISiteSigninHandler):
    """
    SunnyPT签到
    """

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "sunnypt.top"

    @staticmethod
    def _bearer_auth(value: str) -> str:
        """
        将 Authorization Token 规范化为 Bearer 认证值。
        """
        return value if value.lower().startswith("bearer ") else f"Bearer {value}"

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")
        token = site_info.get("token")

        # 替换默认 User-Agent
        if ua and ua == settings.USER_AGENT:
            ua = settings.NORMAL_USER_AGENT

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        domain = StringUtils.get_url_domain(url)
        signin_url = f"https://api.{domain}/api/v1/attendance/check-in"

        if not token:
            logger.warning(f"{site} 签到失败，未配置请求头")
            return False, '签到失败，未配置请求头'

        headers = {
            "Authorization": self._bearer_auth(token),
            "User-Agent": ua,
            "Referer": url
        }

        # 签到
        html_text = self.post_res(url=signin_url,
                                  headers=headers,
                                  proxy=proxy,
                                  timeout=timeout,
                                  check_code=False)

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        sign_dict = self.safe_json_loads(html_text)
        if not sign_dict:
            logger.warning(f"{site} 签到失败，签到数据解析失败：\n{html_text}")
            return False, '签到失败，签到数据解析失败'

        code = sign_dict.get("code")
        if code == 401000:
            logger.warning(f"{site} 签到失败，Token已失效")
            return False, '签到失败，Token已失效'
        if code == 400001:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'
        if code == 0:
            points = sign_dict.get("data", {}).get("points")
            logger.info(f'{site} 签到成功，获得{points}魔力值')
            return True, "签到成功"

        logger.warning(f"{site} 签到失败，{sign_dict.get('msg')}")
        return False, '签到失败，请查看日志'

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")
        token = site_info.get("token")

        # 替换默认 User-Agent
        if ua and ua == settings.USER_AGENT:
            ua = settings.NORMAL_USER_AGENT

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        domain = StringUtils.get_url_domain(url)
        login_url = f"https://api.{domain}/api/v1/user/basic-info"

        if not token:
            logger.warning(f"{site} 模拟登录失败，未配置请求头")
            return False, '模拟登录失败，未配置请求头'

        headers = {
            "Authorization": self._bearer_auth(token),
            "User-Agent": ua,
            "Referer": url
        }

        # 获取用户信息，更新最后访问时间
        html_text = self.get_page_source(url=login_url,
                                         headers=headers,
                                         proxy=proxy,
                                         timeout=timeout,
                                         check_code=False)

        if not html_text:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'

        info_dict = self.safe_json_loads(html_text)
        if not info_dict:
            logger.warning(f"{site} 模拟登录失败，登录数据解析失败：\n{html_text}")
            return False, '模拟登录失败，登录数据解析失败'

        code = info_dict.get("code")
        if code == 400000:
            logger.warning(f"{site} 模拟登录失败，Token已失效")
            return False, '模拟登录失败，Token已失效'
        if code == 0:
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"

        logger.warning(f"{site} 模拟登录失败，{info_dict.get('msg')}")
        return False, '模拟登录失败，请查看日志'
