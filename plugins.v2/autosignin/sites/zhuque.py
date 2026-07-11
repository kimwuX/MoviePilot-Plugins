from typing import Tuple
from urllib.parse import urljoin

from lxml import etree
from ruamel.yaml import CommentedMap

from app.log import logger
from app.plugins.autosignin.sites import _ISiteSigninHandler


class ZhuQue(_ISiteSigninHandler):
    """
    朱雀签到
    """

    @staticmethod
    def get_netloc():
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        return "zhuque.in"

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
        signin_url = urljoin(url, "/api/gaming/fireGenshinCharacterMagic")

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

        if "login.php" in html_text:
            logger.warning(f"{site} 签到失败，Cookie已失效")
            return False, '签到失败，Cookie已失效'

        html = etree.HTML(html_text)
        if not html:
            logger.warning(f"{site} 签到失败，无法解析：\n{html_text}")
            return False, f'签到失败，无法解析文档'

        x_csrf_token = html.xpath("//meta[@name='x-csrf-token']/@content")
        if not x_csrf_token:
            logger.warning(f"{site} 签到失败，签到参数获取失败")
            return False, '签到失败，签到参数获取失败'

        headers = {
            "x-csrf-token": str(x_csrf_token[0]),
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": ua
        }
        data = {
            "all": 1,
            "resetModal": "true"
        }

        # 释放技能
        html_sign = self.post_res(url=signin_url,
                                  headers=headers,
                                  cookies=cookies,
                                  proxy=proxy,
                                  timeout=timeout,
                                  json=data)

        if not html_sign:
            logger.warning(f"{site} 签到失败，签到接口请求失败")
            return False, '签到失败，签到接口请求失败'

        sign_dict = self.safe_json_loads(html_sign)
        if not sign_dict:
            logger.warning(f"{site} 签到失败，签到数据解析失败：\n{html_sign}")
            return False, '签到失败，签到数据解析失败'

        # '{"status":200,"data":{"code":"FIRE_GENSHIN_CHARACTER_MAGIC_SUCCESS","bonus":0}}'
        if sign_dict.get("status") == 200:
            bonus = int(sign_dict['data']['bonus'])
            logger.info(f'{site} 签到成功，获得{bonus}魔力')
            return True, f'签到成功'

        logger.warning(f"{site} 签到失败，接口返回：\n{html_sign}")
        return False, '签到失败，请查看日志'
