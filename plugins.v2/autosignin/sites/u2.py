import datetime
import random
from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class U2(_ISiteSigninHandler):
    """
    U2签到
    """

    # 已签到
    _sign_regex = ['<a href="showup.php">已签到</a>',
                   '<a href="showup.php">Show Up</a>',
                   '<a href="showup.php">Показать</a>',
                   '<a href="showup.php">已簽到</a>',
                   '<a href="showup.php">已簽到</a>']

    # 签到成功
    # <script type="text/javascript">window.location.href = 'showup.php';</script>
    # <script type="text/javascript">window.location.href = 'https://u2.dmhy.org/showup.php';</script>
    _succeed_regex = [r'<script type="text\/javascript">'
                      r"window\.location\.href\s*=\s*'(?:https:\/\/u2\.dmhy\.org\/)?showup\.php';"
                      r'<\/script>']

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "u2.dmhy.org"

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

        # 替换默认 User-Agent
        if ua and ua == settings.USER_AGENT:
            ua = settings.NORMAL_USER_AGENT

        now = datetime.datetime.now()
        # 判断当前时间是否小于9点
        if now.hour < 9:
            logger.warning(f"{site} 签到失败，9点前不签到")
            return False, '签到失败，9点前不签到'

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/showup.php")

        # 获取页面html
        html_text = self.get_page_source(url=signin_url,
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

        # 没有签到则解析html
        html = etree.HTML(html_text)
        if not html:
            logger.warning(f"{site} 签到失败，无法解析：\n{html_text}")
            return False, f'签到失败，无法解析文档'

        # 获取签到参数
        req = html.xpath("//form//input[@name='req']/@value")
        hash_str = html.xpath("//form//input[@name='hash']/@value")
        form = html.xpath("//form//input[@name='form']/@value")
        csrf_token = html.xpath("//form//input[@name='_csrf']/@value")
        submit_name = html.xpath("//form//td/input[@type='submit']/@name")
        submit_value = html.xpath("//form//td/input[@type='submit']/@value")
        if (
            not req
            or not hash_str
            or not form
            or not csrf_token
            or not submit_name
            or not submit_value
        ):
            logger.warning(f"{site} 签到失败，未获取到相关签到参数")
            return False, '签到失败'

        # 随机一个答案
        answer_num = random.randint(0, 3)
        data = {
            'req': req[0],
            'hash': hash_str[0],
            'form': form[0],
            '_csrf': csrf_token[0],
            'message': '今日份签到',
            submit_name[answer_num]: submit_value[answer_num]
        }

        # 签到
        html_sign = self.post_res(url=signin_url + "?action=show",
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
        if self.test_re(text=html_sign, regexs=self._succeed_regex):
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_sign}")
        return False, '签到失败，请查看日志'
