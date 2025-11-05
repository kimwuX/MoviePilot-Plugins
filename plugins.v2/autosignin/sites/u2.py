import datetime
import random
import re
from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils


class U2(_ISiteSigninHandler):
    """
    U2签到 随机
    """

    # 已签到
    _sign_regex = ['<a href="showup.php">已签到</a>',
                   '<a href="showup.php">Show Up</a>',
                   '<a href="showup.php">Показать</a>',
                   '<a href="showup.php">已簽到</a>',
                   '<a href="showup.php">已簽到</a>']

    # 签到成功
    _success_text = "window.location.href = 'showup.php';</script>"

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
        site_cookie = site_info.get("cookie")
        # ua = site_info.get("ua")
        ua = settings.NORMAL_USER_AGENT
        proxy = site_info.get("proxy")
        render = site_info.get("render")
        timeout = site_info.get("timeout")

        now = datetime.datetime.now()
        # 判断当前时间是否小于9点
        if now.hour < 9:
            logger.warning(f"{site} 签到失败，9点前不签到")
            return False, '签到失败，9点前不签到'

        logger.info(f"开始以 {self.__class__.__name__} 模型签到 {site}")
        signin_url = urljoin(url, "/showup.php?action=show")

        # 获取页面html
        html_text = self.get_page_source(url=urljoin(url, "/showup.php"),
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

        # 判断是否已签到
        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._sign_regex)
        if sign_status:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_text)
        if not html:
            return False, f'签到失败，无法解析：\n{html_text}'

        # 获取签到参数
        req = html.xpath("//form//td/input[@name='req']/@value")[0]
        hash_str = html.xpath("//form//td/input[@name='hash']/@value")[0]
        form = html.xpath("//form//td/input[@name='form']/@value")[0]
        submit_name = html.xpath("//form//td/input[@type='submit']/@name")
        submit_value = html.xpath("//form//td/input[@type='submit']/@value")
        if not re or not hash_str or not form or not submit_name or not submit_value:
            logger.warning(f"{site} 签到失败，未获取到相关签到参数")
            return False, '签到失败'

        # 随机一个答案
        answer_num = random.randint(0, 3)
        data = {
            'req': req,
            'hash': hash_str,
            'form': form,
            'message': '今日份签到',
            submit_name[answer_num]: submit_value[answer_num]
        }
        # 签到
        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).post_res(url=signin_url, data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 判断是否签到成功
        # sign_res.text = "<script type="text/javascript">window.location.href = 'showup.php';</script>"
        if self._success_text in sign_res.text:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{sign_res.text}")
        return False, '签到失败，请查看日志'
