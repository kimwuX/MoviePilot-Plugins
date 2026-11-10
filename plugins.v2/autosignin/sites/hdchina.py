from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class HDChina(_ISiteSigninHandler):
    """
    瓷器签到
    """

    # 已签到
    _sign_regex = ['<a class="label label-default" href="#">已签到</a>']

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "hdwing.org"

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
        timeout = site_info.get("timeout")

        # 替换默认 User-Agent
        if ua and ua == settings.USER_AGENT:
            ua = settings.NORMAL_USER_AGENT

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/plugin_sign-in.php?cmd=signin")

        # 尝试解决瓷器cookie每天签到后过期,只保留hdchina=部分
        new_cookies = ";".join([ck for ck in cookies.split(";") if ck.startswith("hdchina=")])
        if "hdchina=" not in new_cookies:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        # 获取页面html
        html_res = RequestUtils(ua=ua,
                                cookies=new_cookies,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).get_res(url=url)
        if not html_res or html_res.status_code != 200:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        html_res.encoding = "utf-8"
        if "takelogin.php" in html_res.text or "阻断页面" in html_res.text:
            logger.warning(f"{site} 签到失败，Cookie失效")
            return False, '签到失败，Cookie失效'

        # 判断是否已签到
        if self.test_re(text=html_res.text, regexs=self._sign_regex):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_res.text)
        if not html:
            logger.warning(f"{site} 签到失败，无法解析：\n{html_res.text}")
            return False, f'签到失败，无法解析文档'

        # x_csrf
        x_csrf = html.xpath("//meta[@name='x-csrf']/@content")[0]
        if not x_csrf:
            logger.warning(f"{site} 签到失败，签到参数获取失败")
            return False, '签到失败，签到参数获取失败'

        logger.debug(f"{site} x-csrf: {x_csrf}")

        # 签到
        data = {
            'csrf': x_csrf
        }
        logger.debug(f"{site} 签到请求参数：{data}")

        # 获取新返回的cookie进行签到
        new_cookies = ';'.join(['{}={}'.format(k, v) for k, v in html_res.cookies.get_dict().items()])
        sign_res = RequestUtils(ua=ua,
                                cookies=new_cookies,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).post_res(url=signin_url, data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = self.safe_json_loads(sign_res.text)
        # {'state': 'success', 'signindays': 10, 'integral': 20}
        if sign_dict and sign_dict['state']:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        # {'state': false, 'msg': '不正确的CSRF / Incorrect CSRF token'}
        logger.warning(f"{site} 签到失败，接口返回：\n{sign_res.text}")
        return False, '签到失败，请查看日志'
