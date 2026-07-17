import re
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class TTG(_ISiteSigninHandler):
    """
    TTG签到
    """

    # 已签到
    _sign_regex = ['<b style="color:green;">已签到</b>']
    _sign_text = '亲，您今天已签到过，不要太贪哦'
    # 签到成功
    _success_text = '您已连续签到'

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "totheglory.im"

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
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/signed.php")

        # 获取页面html
        html_text = self.get_page_source(url=url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "takelogin.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        # 判断是否已签到
        if self.test_re(text=html_text, regexs=self._sign_regex):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 获取签到参数
        signed_timestamp = re.search('(?<=signed_timestamp: ")\\d{10}', html_text).group()
        signed_token = re.search('(?<=signed_token: ").*(?=")', html_text).group()
        logger.debug(f"{site} signed_timestamp={signed_timestamp} signed_token={signed_token}")

        data = {
            'signed_timestamp': signed_timestamp,
            'signed_token': signed_token
        }

        # 签到
        html_sign = self.post_res(url=signin_url,
                                  ua=ua,
                                  cookies=cookies,
                                  proxy=proxy,
                                  timeout=timeout,
                                  data=data)

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 您已连续签到100天，奖励100积分，明天继续签到将获得100积分奖励。
        if self._success_text in html_sign:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        # 亲，您今天已签到过，不要太贪哦。欢迎明天再来！
        if self._sign_text in html_sign:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_sign}")
        return False, '签到失败，请查看日志'
