import json
import os
import time
from io import BytesIO
from typing import Tuple
from urllib.parse import urljoin

from PIL import Image
from lxml import etree
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class Tjupt(_ISiteSigninHandler):
    """
    北洋签到
    """

    # 已签到
    _sign_regex = ['<a href="attendance.php">今日已签到</a>']
    # 签到成功
    _succeed_regex = [r'本次签到获得\s*<b>\d+<\/b>\s*个魔力值']

    _signin_path = "/attendance.php"
    # 签到地址
    _signin_url = "https://www.tjupt.org/attendance.php"

    # 存储答案的文件
    _answer_file = None

    def __init__(self):
        self._answer_file = self.get_data_path("tjupt.json")
        logger.debug(f"答案文件路径：{self._answer_file}")

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "www.tjupt.org"

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

        self._signin_url = urljoin(url, self._signin_path)
        logger.info(f"开始签到 {site}，地址：{self._signin_url}")

        # 获取北洋签到页面html
        html_text = self.get_page_source(url=self._signin_url,
                                         cookie=site_cookie,
                                         ua=ua,
                                         proxy=proxy,
                                         render=render,
                                         timeout=timeout)

        # 获取签到后返回html，判断是否签到成功
        if not html_text:
            logger.warning(f"{site} 签到失败，请检查站点连通性")
            return False, '签到失败，请检查站点连通性'

        if "login.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        sign_status = self.sign_in_result(html_res=html_text,
                                          regexs=self._sign_regex)
        if sign_status:
            logger.info(f"{site} 今日已签到")
            return True, '今日已签到'

        # 没有签到则解析html
        html = etree.HTML(html_text)
        if not html:
            return False, f'签到失败，无法解析：\n{html_text}'

        img_url = html.xpath('//table[@class="captcha"]//img/@src')[0]

        if not img_url:
            logger.warning(f"{site} 签到失败，未获取到签到图片")
            return False, '签到失败，未获取到签到图片'

        # 签到图片
        img_name = img_url.split('/').pop()
        img_url = urljoin(url, img_url)
        logger.info(f"{site} 获取到签到图片 {img_url}")

        # 签到答案选项
        values = html.xpath("//input[@name='ban_robot']/@value")
        options = html.xpath("//input[@name='ban_robot']/following-sibling::text()")

        if not values or not options:
            logger.warning(f"{site} 签到失败，未获取到答案选项")
            return False, '签到失败，未获取到答案选项'

        # value+选项
        answers = list(zip(values, options))
        logger.debug(f"{site} 获取到所有签到选项 {answers}")

        # 查询已有答案
        exits_answers = {}
        try:
            with open(self._answer_file, 'r', encoding='utf-8') as f:
                json_str = f.read()
            exits_answers = json.loads(json_str)
            # 查询本地本次验证码hash答案
            captcha_answer = exits_answers.get(img_name)
            logger.debug(f"{site} 本地答案：{captcha_answer}")

            # 本地存在本次hash对应的正确答案再遍历查询
            if captcha_answer:
                for value, answer in answers:
                    if captcha_answer == answer:
                        # 确实是答案
                        return self.__signin(value=value,
                                             answer=answer,
                                             site=site,
                                             site_cookie=site_cookie,
                                             ua=ua,
                                             proxy=proxy,
                                             timeout=timeout)

            logger.info(f"{site} 本地未收录该答案，继续请求豆瓣查询")
        except Exception as e:
            logger.debug(f"{site} 查询本地已知答案失败：{str(e)}，继续请求豆瓣查询")

        # 获取签到图片hash
        captcha_img_res = RequestUtils(cookies=site_cookie,
                                       ua=ua,
                                       proxies=settings.PROXY if proxy else None,
                                       timeout=timeout
                                       ).get_res(url=img_url)
        if not captcha_img_res or captcha_img_res.status_code != 200:
            logger.warning(f"{site} 签到图片 {img_url} 请求失败")
            return False, '签到失败，未获取到签到图片'
        captcha_img = Image.open(BytesIO(captcha_img_res.content))
        captcha_img_hash = self._tohash(captcha_img)
        logger.debug(f"{site} 签到图片hash {captcha_img_hash}")

        # 本地不存在正确答案则请求豆瓣查询匹配
        for value, answer in answers:
            if answer:
                # 间隔5s，防止请求太频繁被豆瓣屏蔽ip
                time.sleep(5)

                # 豆瓣检索
                db_res = RequestUtils(ua=settings.NORMAL_USER_AGENT
                                      ).get_res(url=f'https://movie.douban.com/j/subject_suggest?q={answer}')
                logger.debug(f"{site} 豆瓣返回 {answer} {db_res.text}")
                if not db_res or db_res.status_code != 200:
                    logger.debug(f"{site} 签到选项 {answer} 未查询到豆瓣数据")
                    continue

                # 豆瓣返回结果
                db_answers = json.loads(db_res.text)
                if not isinstance(db_answers, list):
                    db_answers = [db_answers]

                if len(db_answers) == 0:
                    logger.debug(f"{site} 签到选项 {answer} 查询到豆瓣数据为空")

                for db_answer in db_answers:
                    answer_img_url = db_answer.get('img')
                    answer_title = db_answer.get('title')

                    # 获取答案hash
                    answer_img_res = RequestUtils(referer="https://movie.douban.com").get_res(url=answer_img_url)
                    logger.debug(f"{site} 签到答案图片 {answer_title} {answer_img_url}")
                    if not answer_img_res or answer_img_res.status_code != 200:
                        logger.debug(f"{site} 签到答案 {answer_title} {answer_img_url} 请求失败")
                        continue

                    answer_img = Image.open(BytesIO(answer_img_res.content))
                    answer_img_hash = self._tohash(answer_img)
                    logger.debug(f"{site} 签到答案图片hash {answer_title} {answer_img_hash}")

                    # 获取选项图片与签到图片相似度，大于0.9默认是正确答案
                    score = self._comparehash(captcha_img_hash, answer_img_hash)
                    logger.info(f"{site} 签到图片与 {answer_title} 豆瓣图片相似度 {score}")
                    if score > 0.9:
                        # 确实是答案
                        return self.__signin(value=value,
                                             answer=answer,
                                             site=site,
                                             site_cookie=site_cookie,
                                             ua=ua,
                                             proxy=proxy,
                                             timeout=timeout,
                                             exits_answers=exits_answers,
                                             img_name=img_name)

        logger.warning(f"{site} 海报【{img_name}】签到失败，答案选项：{options}")

        return False, '签到失败，未获取到匹配答案'

    def __signin(self, value: str,
                 answer: str,
                 site: str,
                 site_cookie: str,
                 ua: str,
                 proxy: bool,
                 timeout: int,
                 exits_answers: dict = None,
                 img_name: str = None) -> Tuple[bool, str]:
        """
        签到请求
        """
        data = {
            'ban_robot': value,
            'submit': '提交'
        }
        logger.debug(f"{site} 签到请求参数：{data}")
        sign_res = RequestUtils(cookies=site_cookie,
                                ua=ua,
                                proxies=settings.PROXY if proxy else None,
                                timeout=timeout
                                ).post_res(url=self._signin_url, data=data)
        if not sign_res or sign_res.status_code != 200:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        # 获取签到后返回html，判断是否签到成功
        sign_status = self.sign_in_result(html_res=sign_res.text,
                                          regexs=self._succeed_regex)
        if sign_status:
            if exits_answers is not None and img_name is not None:
                # 签到成功写入本地文件
                self.__write_local_answer(exits_answers=exits_answers,
                                          img_name=img_name,
                                          answer=answer)
            logger.info(f"{site} 签到成功")
            return True, '签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{sign_res.text}")
        return False, '签到失败，请查看日志'

    def __write_local_answer(self, exits_answers, img_name, answer):
        """
        签到成功写入本地文件
        """
        try:
            exits_answers[img_name] = answer
            # 序列化数据
            formatted_data = json.dumps(exits_answers, ensure_ascii=False)
            logger.debug(f"保存答案 {formatted_data}")
            with open(self._answer_file, 'w', encoding='utf-8') as f:
                f.write(formatted_data)
        except Exception as e:
            logger.debug(f"写入本地文件失败：{str(e)}")

    @staticmethod
    def _tohash(img, shape=(10, 10)):
        """
        获取图片hash
        """
        img = img.resize(shape)
        gray = img.convert('L')
        s = 0
        hash_str = ''
        for i in range(shape[1]):
            for j in range(shape[0]):
                s = s + gray.getpixel((j, i))
        avg = s / (shape[0] * shape[1])
        for i in range(shape[1]):
            for j in range(shape[0]):
                if gray.getpixel((j, i)) > avg:
                    hash_str = hash_str + '1'
                else:
                    hash_str = hash_str + '0'
        return hash_str

    @staticmethod
    def _comparehash(hash1, hash2, shape=(10, 10)):
        """
        比较图片hash
        返回相似度
        """
        n = 0
        if len(hash1) != len(hash2):
            return -1
        for i in range(len(hash1)):
            if hash1[i] == hash2[i]:
                n = n + 1
        return n / (shape[0] * shape[1])
