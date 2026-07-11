from datetime import datetime
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class YemaPT(_ISiteSigninHandler):
    """
    YemaPT签到
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
        cookies = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        checklist_url = urljoin(url, "/api/consumer/fetchCheckInPageInfo")
        signin_url = urljoin(url, "/api/consumer/checkInNext")

        # 签到记录
        html_text = self.get_page_source(url=checklist_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         timeout=timeout,
                                         referer=url,
                                         accept_type="application/json, text/plain, */*")

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        record_dict = self.safe_json_loads(html_text)
        if not record_dict:
            logger.warning(f"{site} 签到失败，签到记录解析失败：\n{html_text}")
            return False, '签到失败，签到记录解析失败'

        if not record_dict.get("success"):
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        # today = datetime.now().strftime("%Y%m%d")
        # for day in record_dict.get("data"):
        #     if str(day.get("checkDay")) == today:
        #         logger.info(f"{site} 今日已签到")
        #         return True, '今日已签到'
        if record_dict.get("data") and record_dict.get("data").get("checkedInToday"):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 签到
        html_sign = self.post_res(url=signin_url,
                                  ua=ua,
                                  cookies=cookies,
                                  proxy=proxy,
                                  timeout=timeout,
                                  referer=url,
                                  content_type="application/json",
                                  accept_type="application/json, text/plain, */*",
                                  json={})

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = self.safe_json_loads(html_sign)
        if not sign_dict:
            logger.warning(f"{site} 签到失败，签到数据解析失败：\n{html_sign}")
            return False, '签到失败，签到数据解析失败'

        if sign_dict.get("success"):
            logger.info(f"{site} 签到成功")
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
        cookies = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        # render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        login_url = urljoin(url, "/api/user/profile")

        # 获取用户信息，更新最后访问时间
        html_text = self.get_page_source(url=login_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         timeout=timeout,
                                         referer=url,
                                         accept_type="application/json, text/plain, */*")

        if not html_text:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'

        res_dict = self.safe_json_loads(html_text)
        if not res_dict:
            logger.warning(f"{site} 模拟登录失败，登录数据解析失败：\n{html_text}")
            return False, '模拟登录失败，登录数据解析失败'

        if res_dict.get("success"):
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"

        logger.warning(f"{site} 模拟登录失败，接口返回：\n{html_text}")
        return False, '模拟登录失败，请查看日志'
