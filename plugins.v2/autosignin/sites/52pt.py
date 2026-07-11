import re
from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class PT52(_ISiteSigninHandler):
    """
    52pt签到
    """

    # 已签到
    _sign_regex = ['今天已经签过到了']
    # 签到成功
    # 连续签到 84 天，获得 127 魔力值
    _success_regex = [r'连续签到\s*\d+\s*天，获得\s*\d+\s*魔力值']

    # 签到路径
    _signin_path = "/52bakatest0618.php"

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "52pt.site"

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        url = site_info.get("url")
        # ua = site_info.get("ua")
        ua = settings.NORMAL_USER_AGENT
        cookies = site_info.get("cookie")
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, self._signin_path)

        # 判断今日是否已签到
        html_text = self.get_page_source(url=signin_url,
                                         ua=ua,
                                         cookies=cookies,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout,
                                         referer=url)

        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        if self.test_re(text=html_text, regexs=self._sign_regex):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_text)
        if not html:
            logger.warning(f"{site} 签到失败，无法解析：\n{html_text}")
            return False, f'签到失败，无法解析文档'

        # 获取验证码
        # captchaInput.value = '4499'
        mat_captcha = None
        script_text = html.xpath("//td[@id='outer']/script/text()")
        if script_text:
            mat_captcha = re.search(r"captchaInput\.value\s*=\s*'(\d+)'", script_text[0])
        if not mat_captcha:
            logger.warning(f"{site} 签到失败，签到参数[sign_captcha]获取失败")
            return False, '签到失败，签到参数获取失败'

        sign_token = html.xpath("//input[@name='sign_token']/@value")
        if not sign_token:
            logger.warning(f"{site} 签到失败，签到参数[sign_token]获取失败")
            return False, '签到失败，签到参数获取失败'

        sign_submit = html.xpath("//input[@name='sign_submit']/@value")
        if not sign_submit:
            logger.warning(f"{site} 签到失败，签到参数[sign_submit]获取失败")
            return False, '签到失败，签到参数获取失败'

        logger.debug(f'{site} mat_captcha: {mat_captcha.group()}')
        logger.debug(f'{site} sign_token: {sign_token}')
        logger.debug(f'{site} sign_submit: {sign_submit}')

        # 组装请求参数
        data = {
            'sign_captcha': mat_captcha[1],
            'sign_token': sign_token[0],
            'sign_submit': sign_submit[0]
        }
        logger.debug(f"{site} 签到请求参数：{data}")

        # 签到
        html_sign = self.post_res(url=signin_url,
                                  ua=ua,
                                  cookies=cookies,
                                  proxy=proxy,
                                  timeout=timeout,
                                  referer=signin_url,
                                  data=data)

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 判断是否签到成功
        if self.test_re(text=html_sign, regexs=self._success_regex):
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        if self.test_re(text=html_sign, regexs=self._sign_regex):
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_sign}")
        return False, '签到失败，请查看日志'
