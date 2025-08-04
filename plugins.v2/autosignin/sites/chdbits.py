import json
import os
import random
import re
from typing import Tuple

from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class CHDBits(_ISiteSigninHandler):
    """
    彩虹岛签到
    如果填写openai key则调用chatgpt获取答案
    否则随机
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "ptchdbits.co"

    # 签到地址
    _sign_in_url = 'https://ptchdbits.co/bakatest.php'

    # 已签到
    _sign_regex = ['今天已经签过到了']

    # 签到成功，待补充
    _success_regex = ['\\d+点魔力值']

    # 存储正确的答案，后续可直接查
    _answer_path = settings.TEMP_PATH / "signin/"
    _answer_file = _answer_path / "chdbits.json"

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        # ua = site_info.get("ua")
        ua = settings.NORMAL_USER_AGENT
        proxy = site_info.get("proxy")
        render = site_info.get("render")

        # 创建正确答案存储目录
        if not os.path.exists(os.path.dirname(self._answer_file)):
            os.makedirs(os.path.dirname(self._answer_file))

        # 判断今日是否已签到
        html_text = self.get_page_source(url=self._sign_in_url,
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render)

        if not html_text:
            logger.error(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.error(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._sign_regex)
        if sign_status:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_text)

        if not html:
            return False, '签到失败'

        # 获取页面问题、答案
        questionid = html.xpath("//input[@name='questionid']/@value")[0]
        # option_ids = html.xpath("//input[@name='choice[]']/@value")
        question_str = html.xpath("//td[@class='text' and contains(text(),'请问：')]/text()")[0]

        logger.debug(f"签到问题：{questionid} {question_str.strip()}")

        # 查询已有答案
        try:
            with open(self._answer_file, 'r', encoding='utf-8') as f:
                json_str = f.read()
            exits_answers = json.loads(json_str)
            choice = exits_answers.get(questionid)
            logger.debug(f"本地答案：{choice}")

            # 本地存在答案
            if choice:
                return self.__signin(questionid=questionid,
                                     choice=choice,
                                     site=site,
                                     site_cookie=site_cookie,
                                     ua=ua,
                                     proxy=proxy)
        except Exception as e:
            logger.debug(f"查询本地已知答案失败：{str(e)}")

        return False, '签到失败，未收录该题答案'

    def __signin(self, questionid: str, choice: list, site: str, site_cookie: str, ua: str, proxy: bool) -> Tuple[bool, str]:
        """
        签到请求
        questionid: 450
        choice[]: 8
        choice[]: 4
        usercomment: 此刻心情:无
        submit: 提交
        多选会有多个choice[]....
        """
        data = {
            'questionid': questionid,
            'choice[]': choice[0] if len(choice) == 1 else choice,
            'usercomment': '马马虎虎~',
            'submit': '提交'
        }
        logger.debug(f"签到请求参数 {data}")

        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None
                                ).post_res(url=self._sign_in_url, data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.error(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 判断是否签到成功
        sign_status = self.sign_in_result(html_res=sign_res.text,
                                          regexs=self._success_regex)
        if sign_status:
            logger.info(f"{site} 签到成功")
            return True, '签到成功'
        else:
            sign_status = self.sign_in_result(html_res=sign_res.text,
                                              regexs=self._sign_regex)
            if sign_status:
                logger.info(f"{site} 今日已签到")
                return True, '今日已签到'

            logger.error(f"{site} 签到失败，请到页面查看")
            return False, '签到失败，请到页面查看'
