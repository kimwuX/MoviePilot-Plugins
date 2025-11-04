import json
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.string import StringUtils


class PTerClub(_ISiteSigninHandler):
    """
    猫签到
    """

    _signin_path = "/attendance-ajax.php"
    # 签到地址
    _signin_url = "https://pterclub.com/attendance-ajax.php"

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return ["pterclub.com", "pterclub.net"]

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

        self._signin_url = urljoin(url, self._signin_path)
        logger.info(f"开始签到 {site}，地址：{self._signin_url}")

        # 签到
        html_text = self.get_page_source(url=self._signin_url,
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

        try:
            sign_dict = json.loads(html_text)
        except Exception as e:
            logger.warning(f"{site} 签到失败，错误信息：\n{str(e)}")
            return False, '签到失败，未知错误'

        if sign_dict['status'] == '1':
            # {"status":"1","data":" (签到已成功300)","message":"<p>这是您的第<b>237</b>次签到，
            # 已连续签到<b>237</b>天。</p><p>本次签到获得<b>300</b>克猫粮。</p>"}
            logger.info(f"{site} 签到成功")
            return True, '签到成功'
        else:
            # {"status":"0","data":"抱歉","message":"您今天已经签到过了，请勿重复刷新。"}
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'
