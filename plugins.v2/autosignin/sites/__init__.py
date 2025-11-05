# -*- coding: utf-8 -*-
import re
from abc import ABCMeta, abstractmethod
from pathlib import Path
from typing import Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.helper.browser import PlaywrightHelper
from app.log import logger
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class _ISiteSigninHandler(metaclass=ABCMeta):
    """
    实现站点签到的基类，所有站点签到类都需要继承此类，并实现match和signin方法
    实现类放置到sitesignin目录下将会自动加载
    """

    @classmethod
    def match_url(self, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        netloc = self.get_netloc()
        if isinstance(netloc, list):
            return any(StringUtils.url_equal(url, s) for s in netloc)
        elif isinstance(netloc, str):
            return StringUtils.url_equal(url, netloc)
        else:
            return False

    @classmethod
    def match_schema(self, schema: str) -> bool:
        """
        根据站点Schema判断是否匹配当前站点签到类
        :param schema: 站点Schema
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return schema and schema.lower() == self.get_schema()

    @abstractmethod
    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: True|False,签到结果信息
        """
        pass

    @staticmethod
    def get_netloc() -> Tuple[str, list]:
        """
        获取当前站点域名，可以是单个或者多个域名
        """
        pass

    @staticmethod
    def get_schema() -> str:
        """
        获取当前站点模型，只有通用模型需要返回值
        """
        pass

    @staticmethod
    def get_page_source(url: str, cookie: str, ua: str, proxy: bool, render: bool,
                        token: str = None, timeout: int = None) -> str:
        """
        获取页面源码
        :param url: Url地址
        :param cookie: Cookie
        :param ua: UA
        :param proxy: 是否使用代理
        :param render: 是否渲染
        :param token: JWT Token
        :param timeout: 请求超时时间，单位秒
        :return: 页面源码，错误信息
        """
        if render:
            return PlaywrightHelper().get_page_source(url=url,
                                                      cookies=cookie,
                                                      ua=ua,
                                                      proxies=settings.PROXY_SERVER if proxy else None,
                                                      timeout=timeout or 60)
        else:
            if token:
                headers = {
                    "Authorization": token,
                    "User-Agent": ua
                }
            else:
                headers = {
                    "User-Agent": ua,
                    "Cookie": cookie
                }
            req = RequestUtils(headers=headers,
                               proxies=settings.PROXY if proxy else None,
                               timeout=timeout or 20
                               ).get_res(url=url, allow_redirects=False)
            while req and req.status_code in [301, 302] and req.headers['Location']:
                logger.info(f"重定向 {url} -> {req.headers['Location']}")
                url = urljoin(url, req.headers['Location'])
                req = RequestUtils(headers=headers,
                                   proxies=settings.PROXY if proxy else None,
                                   timeout=timeout or 20
                                   ).get_res(url=url, allow_redirects=False)
            if req is not None:
                # 使用chardet检测字符编码
                raw_data = req.content
                if raw_data:
                    try:
                        return raw_data.decode()
                    except Exception as e:
                        logger.error(f"{url} 页面解码失败：{str(e)}")
                        return req.text
                else:
                    return req.text
            return ""

    @staticmethod
    def sign_in_result(html_res: str, regexs: list) -> bool:
        """
        判断是否签到成功
        """
        html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_res))
        for regex in regexs:
            if re.search(str(regex), html_text):
                return True
        return False

    @staticmethod
    def get_data_path(filename: str) -> Path:
        """
        获取插件数据保存路径
        """
        data_path = settings.PLUGIN_DATA_PATH / "autosignin"
        if not data_path.exists():
            data_path.mkdir(parents=True)
        if filename:
            data_path = data_path / filename
        return data_path
