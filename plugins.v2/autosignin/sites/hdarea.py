from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class HDArea(_ISiteSigninHandler):
    """
    好大签到
    """

    # 已连续签到278天，此次签到您获得了100魔力值奖励!
    _success_text = "此次签到您获得"
    # 请不要重复签到哦！
    _repeat_text = "请不要重复签到哦"

    _signin_path = "/sign_in.php"
    # 签到地址
    _signin_url = "https://hdarea.club/sign_in.php"

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "hdarea.club"

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
        timeout = site_info.get("timeout")

        self._signin_url = urljoin(url, self._signin_path)
        logger.info(f"开始签到 {site}，地址：{self._signin_url}")

        # 获取页面html
        data = {
            'action': 'sign_in'
        }
        html_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).post_res(url=self._signin_url, data=data)
        if not html_res or html_res.status_code != 200:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_res.text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        # 判断是否已签到
        if self._success_text in html_res.text:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'
        if self._repeat_text in html_res.text:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_res.text}")
        return False, '签到失败，请查看日志'
