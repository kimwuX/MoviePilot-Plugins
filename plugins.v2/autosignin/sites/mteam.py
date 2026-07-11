from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.modules.indexer.parser import SiteSchema
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.string import StringUtils


class MTeam(_ISiteSigninHandler):
    """
    馒头签到
    """

    @staticmethod
    def get_schema():
        """
        获取当前站点模型，只有通用模型需要返回值
        """
        return SiteSchema.MTorrent.value

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
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        apikey = site_info.get("apikey")
        token = site_info.get("token")

        logger.info(f"开始以 {self.__class__.__name__} 模型模拟登录 {site}")
        domain = StringUtils.get_url_domain(url)
        login_url = f"https://api.{domain}/api/member/updateLastBrowse"

        if not apikey or not token:
            logger.warning(f"{site} 模拟登录失败，未配置请求头或令牌")
            return False, '模拟登录失败，未配置请求头或令牌'

        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": ua,
            "x-api-key": apikey,
            "Authorization": token
        }
        # 更新最后访问时间
        html_text = self.post_res(url=login_url,
                                  headers=headers,
                                  proxy=proxy,
                                  timeout=timeout)

        if not html_text:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'

        info_dict = self.safe_json_loads(html_text)
        if not info_dict:
            logger.warning(f"{site} 模拟登录失败，登录数据解析失败：\n{html_text}")
            return False, '模拟登录失败，登录数据解析失败'

        code = int(info_dict.get("code", -1))
        if code == 0:
            logger.info(f"{site} 模拟登录成功")
            return True, "模拟登录成功"
        if code == 401:
            logger.warning(f"{site} 模拟登录失败，请求头已过期")
            return False, "模拟登录失败，请求头已过期"

        logger.warning(f"{site} 模拟登录失败，接口返回：\n{html_text}")
        return False, '模拟登录失败，请查看日志'
