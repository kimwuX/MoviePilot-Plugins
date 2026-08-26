import uuid
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class RousiPro(_ISiteSigninHandler):
    """
    RousiPro签到
    """

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "rousi.pro"

    @staticmethod
    def _bearer_auth(value: str) -> str:
        """
        将 API Key 或 Authorization Token 规范化为 Bearer 认证值。
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
        cookies = site_info.get("cookie")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")
        # token = site_info.get("token")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        session_url = urljoin(url, "/api/v1/session")
        signin_url = urljoin(url, "/api/v1/me/attendance")

        # 获取 Token
        html_text = self.get_page_source(url=session_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         timeout=timeout,
                                         referer=url,
                                         check_code=False)

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        session_dict = self.safe_json_loads(html_text)
        if not session_dict:
            logger.warning(f"{site} 签到失败，用户数据解析失败：\n{html_text}")
            return False, '签到失败，用户数据解析失败'

        csrf_token = session_dict.get("csrf_token")
        if not csrf_token:
            logger.warning(f"{site} 签到失败，CSRF_TOKEN获取失败")
            return False, '签到失败，CSRF_TOKEN获取失败'

        headers = {
            "Idempotency-Key": str(uuid.uuid1()),
            "X-Csrf-Token": csrf_token,
            "User-Agent": ua,
            "Origin": url
        }
        # mode=fixed/random
        data = {"mode": "random"}

        # 签到
        html_sign = self.post_res(url=signin_url,
                                  headers=headers,
                                  cookies=cookies,
                                  proxy=proxy,
                                  timeout=timeout,
                                  json=data,
                                  check_code=False)

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = self.safe_json_loads(html_sign)
        if not sign_dict:
            logger.warning(f"{site} 签到失败，签到数据解析失败：\n{html_sign}")
            return False, '签到失败，签到数据解析失败'

        status = sign_dict.get("status")
        if status == 401:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'
        if status == 403:
            logger.warning(f"{site} 签到失败，Token已失效")
            return False, '签到失败，Token已失效'
        if status == 409:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'
        if status:
            logger.warning(f"{site} 签到失败，{sign_dict.get('title')}({sign_dict.get('detail')})")
            return False, '签到失败，请查看日志'

        bonus = sign_dict.get("total_reward")
        if bonus:
            logger.info(f'{site} 签到成功，获得{bonus}魔力值')
            return True, "签到成功"

        logger.warning(f"{site} 签到失败，接口返回：\n{html_sign}")
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
        cookies = site_info.get("cookie")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")
        # token = site_info.get("token")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        login_url = urljoin(url, "/api/v1/session")

        html_text = self.get_page_source(url=login_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         timeout=timeout,
                                         referer=url,
                                         check_code=False)

        if not html_text:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'

        info_dict = self.safe_json_loads(html_text)
        if not info_dict:
            logger.warning(f"{site} 模拟登录失败，登录数据解析失败：\n{html_text}")
            return False, '模拟登录失败，登录数据解析失败'

        if info_dict.get("csrf_token"):
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"

        logger.warning(f"{site} 模拟登录失败，接口返回：\n{html_text}")
        return False, '模拟登录失败，请查看日志'
