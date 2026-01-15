from typing import Optional, Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class RousiPro(_ISiteSigninHandler):
    """
    RousiPro 签到
    """

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "rousi.pro"

    def get_json(self, response) -> Optional[dict]:
        if response is not None:
            try:
                data = response.json()
                return data
            except Exception as e:
                logger.debug(f"解析JSON失败: {e}")
                return None
            # finally:
            #     response.close()
        return None

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        # site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")
        token = site_info.get("token")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/api/points/attendance")

        if not token:
            logger.warning(f"{site} 签到失败，未配置请求头")
            return False, '签到失败，未配置请求头'

        headers = {
            "User-Agent": ua,
            "Content-Type": "application/json",
            "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}"
        }
        # mode=fixed/random
        data = {"mode": "random"}

        # 签到
        res_sign = RequestUtils(headers=headers,
                                # cookies=site_cookie,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout,
                                referer=url
                                ).post_res(url=signin_url, json=data)

        if res_sign is None:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'
        elif res_sign.status_code == 400:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'
        elif res_sign.status_code == 401:
            logger.warning(f"{site} 签到失败，登录状态无效")
            return False, '签到失败，登录状态无效'
        elif res_sign.status_code == 200:
            dict_sign = self.get_json(res_sign)
            if dict_sign and dict_sign.get("bonus"):
                logger.info(f'{site} 签到成功，获得{dict_sign.get("bonus")}魔力值')
                return True, "签到成功"

        logger.warning(f"{site} 签到失败，接口返回：\n{res_sign.text}")
        return False, '签到失败，请查看日志'

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 登录结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        # site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")
        token = site_info.get("token")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        login_url = urljoin(url, "/api/me")

        if not token:
            logger.warning(f"{site} 模拟登录失败，未配置请求头")
            return False, '模拟登录失败，未配置请求头'

        headers = {
            "User-Agent": ua,
            "Authorization": token if token.startswith("Bearer ") else f"Bearer {token}"
        }

        # 获取用户信息，更新最后访问时间
        res_info = RequestUtils(headers=headers,
                                # cookies=site_cookie,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout,
                                referer=url
                                ).get_res(url=login_url)

        if res_info is None:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'
        elif res_info.status_code == 401:
            logger.warning(f"{site} 模拟登录失败，登录状态无效")
            return False, '模拟登录失败，登录状态无效'
        elif res_info.status_code == 200:
            dict_info = self.get_json(res_info)
            if dict_info and dict_info.get("passkey"):
                logger.info(f"{site} 模拟登录成功")
                return True, "模拟登录成功"

        logger.warning(f"{site} 模拟登录失败，接口返回：\n{res_info.text}")
        return False, '模拟登录失败，请查看日志'
