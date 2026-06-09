import re
from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.helper.cloudflare import under_challenge
from app.log import logger
from app.modules.indexer.parser import SiteSchema
from app.plugins.autosignin.sites import _ISiteSigninHandler


class NexusPHP(_ISiteSigninHandler):
    """
    NexusPHP通用签到
    """

    # cloudflare challenge
    _re_cf = [r'cf-turnstile']

    # safeline firewall
    _re_sl = [r'slg-title', r'slg-box', r'sl-box']

    # other chanllenges
    _re_ch = [r'dragContainer', r'dragBg', r'dragText', r'dragHandler']

    # 没有签到功能
    _re_404 = [r'File not found', r'404 Not Found']

    # 已签到
    # ↓ 签到入口 ↓
    # [签到已得100]
    # [签到已得100, 补签卡: 0]
    # [簽到已得100, 補簽卡: 0]
    # [已签到，获得88魔力，补签卡：0张]
    _re_signed_a = [r'签到已得', r'簽到已得', r'已签到', r'已簽到']
    # ↓ 签到结果页面 ↓
    # 您今天已经签到过了，请勿重复刷新。
    _re_signed_s = [r'您今天已经签到过了，请勿重复刷新']

    # 签到成功
    # 这是您的第233次签到，已连续签到233天，本次签到获得1000个憨豆。
    # 这是您的第 <b>233</b> 次签到，已连续签到 <b>233</b> 天，本次签到获得 <b>233</b> 个啤酒瓶。
    # 這是您的第 <b>233</b> 次簽到，已連續簽到 <b>233</b> 天，本次簽到獲得 <b>233</b> 個魔力值。
    # 这是您签到的第 <b>233</b> 次，已经连续签到 <b>233</b> 天啦！这次签到还获得了 <b>233</b> 魔法值哦~
    _re_success = [r'连续签到\s*\S*?\d+\S*?\s*天，本次签到获得',
                   r'連續簽到\s*\S*?\d+\S*?\s*天，本次簽到獲得',
                   r'连续签到\s*\S*?\d+\S*?\s*天啦！这次签到还获得了']

    @staticmethod
    def get_schema():
        """
        获取当前站点模型，只有通用模型需要返回值
        """
        return [SiteSchema.NexusPhp.value,
                SiteSchema.NexusHhanclub.value,
                SiteSchema.NexusAudiences.value,
                SiteSchema.HDDolby.value]

    @classmethod
    def check_html(cls, site: str, html_text: str) -> Tuple[bool, str]:
        if "login.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        if "take2fa.php" in html_text:
            logger.warning(f"{site} 签到失败，两步验证拦截")
            return False, '签到失败，两步验证拦截'

        if under_challenge(html_text):
            logger.warning(f"{site} 签到失败，无法绕过Cloudflare检测")
            return False, '签到失败，无法绕过Cloudflare检测'

        if cls.test_re(text=html_text, regexs=cls._re_sl):
            logger.warning(f"{site} 签到失败，无法绕过雷池检测")
            return False, '签到失败，无法绕过雷池检测'

        if cls.test_re(text=html_text, regexs=cls._re_ch):
            logger.warning(f"{site} 签到失败，无法通过验证")
            return False, '签到失败，无法通过验证'

        if cls.test_re(text=html_text, regexs=cls._re_cf):
            logger.warning(f"{site} 签到失败，签到页面已被Cloudflare防护")
            return False, '签到失败，签到页面已被Cloudflare防护'

        return True, ''

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
        if not url:
            logger.warning(f"{site} 签到失败，未配置站点地址")
            return False, '签到失败，未配置站点地址'

        logger.info(f"开始以 {self.__class__.__name__} 通用模型签到 {site}")
        usercp_url = urljoin(url, "/usercp.php")
        signin_url = urljoin(url, "/attendance.php")

        html_text = self.get_page_source(url=usercp_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        # 页面出错
        state, message = self.check_html(site=site, html_text=html_text)
        if not state:
            return state, message

        # 已签到
        # 解析html
        html = etree.HTML(html_text)
        if html:
            attend_text = html.xpath("//a[@href='attendance.php']/text()")
            if attend_text and self.test_re(text=attend_text[0],
                                            regexs=self._re_signed_a):
                logger.info(f"{site} 今日已签到")
                return True, '今日已签到'

        html_text = self.get_page_source(url=signin_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout,
                                         check_code=False)

        if not html_text:
            logger.warning(f"{site} 签到失败，无法打开签到页面")
            return False, '签到失败，无法打开签到页面'

        if self.test_re(text=html_text, regexs=self._re_404,
                        flags=re.RegexFlag.IGNORECASE):
            logger.warning(f"{site} 签到失败，请确认是否有签到功能")
            return False, '签到失败，请确认是否有签到功能'

        # 页面出错
        state, message = self.check_html(site=site, html_text=html_text)
        if not state:
            return state, message

        # 已签到
        if self.test_re(text=html_text, regexs=self._re_signed_s):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 签到成功
        if self.test_re(text=html_text, regexs=self._re_success):
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_text}")
        return False, '签到失败，请查看日志'

    def login(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行模拟登录操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 模拟登录结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        ua = site_info.get("ua")
        cookies = site_info.get("cookie")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")
        if not url:
            logger.warning(f"{site} 模拟登录失败，未配置站点地址")
            return False, '模拟登录失败，未配置站点地址'

        logger.info(f"开始以 {self.__class__.__name__} 通用模型模拟登录 {site}")
        login_url = urljoin(url, "/index.php")

        html_text = self.get_page_source(url=login_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        if not html_text:
            logger.warning(f"{site} 模拟登录失败，请检查站点连通性")
            return False, '模拟登录失败，请检查站点连通性'

        state, message = self.check_html(site=site, html_text=html_text)
        if not state:
            return state, message

        if "userdetails.php" in html_text:
            logger.info(f"{site} 模拟登录成功")
            return True, '模拟登录成功'

        logger.warning(f"{site} 模拟登录失败，接口返回：\n{html_text}")
        return False, '模拟登录失败，请查看日志'