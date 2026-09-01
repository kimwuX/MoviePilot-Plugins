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
        timeout = site_info.get("timeout")
        apikey = site_info.get("apikey")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/api/points/attendance")

        if not apikey:
            logger.warning(f"{site} 签到失败，未配置令牌")
            return False, '签到失败，未配置令牌'

        headers = {
            "Api-Token": apikey,
            "User-Agent": ua
        }
        # mode=fixed/random
        data = {"mode": "random"}

        # 签到
        html_sign = self.post_res(url=signin_url,
                                  headers=headers,
                                  proxy=proxy,
                                  timeout=timeout,
                                  # referer=url,
                                  json=data,
                                  check_code=False)

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = self.safe_json_loads(html_sign)
        if not sign_dict:
            logger.warning(f"{site} 签到失败，签到数据解析失败：\n{html_sign}")
            return False, '签到失败，签到数据解析失败'

        code = sign_dict.get("code")
        if code == 0:
            bonus = sign_dict.get("data", {}).get("reward")
            if bonus:
                logger.info(f'{site} 签到成功，获得{bonus}魔力值')
            else:
                logger.info(f'{site} 签到成功')
            return True, "签到成功"
        if code == 1:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'
        if code in (401, 403):
            logger.warning(f"{site} 签到失败，令牌已失效或权限不足")
            return False, '签到失败，令牌已失效或权限不足'

        logger.warning(f"{site} 签到失败，{sign_dict.get('message')}")
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
        timeout = site_info.get("timeout")
        apikey = site_info.get("apikey")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        login_url = urljoin(url, "/api/v1/profile")

        if not apikey:
            logger.warning(f"{site} 模拟登录失败，未配置令牌")
            return False, '模拟登录失败，未配置令牌'

        headers = {
            "Api-Token": apikey,
            "User-Agent": ua
        }

        html_text = self.get_page_source(url=login_url,
                                         headers=headers,
                                         proxy=proxy,
                                         timeout=timeout,
                                         # referer=url,
                                         check_code=False)

        if not html_text:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'

        info_dict = self.safe_json_loads(html_text)
        if not info_dict:
            logger.warning(f"{site} 模拟登录失败，登录数据解析失败：\n{html_text}")
            return False, '模拟登录失败，登录数据解析失败'

        code = info_dict.get("code")
        if code == 0:
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"
        if code in (401, 403):
            logger.warning(f"{site} 模拟登录失败，令牌已失效或权限不足")
            return False, '模拟登录失败，令牌已失效或权限不足'

        logger.warning(f"{site} 模拟登录失败，{info_dict.get('message')}")
        return False, '模拟登录失败，请查看日志'
