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
    def match_url(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        netloc = cls.get_netloc()
        if isinstance(netloc, list):
            return any(StringUtils.url_equal(url, s) for s in netloc)
        elif isinstance(netloc, str):
            return StringUtils.url_equal(url, netloc)
        else:
            return False

    @classmethod
    def match_schema(cls, value: str) -> bool:
        """
        根据站点Schema判断是否匹配当前站点签到类
        :param value: 站点Schema
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        schema = cls.get_schema()
        if isinstance(schema, list):
            return value in schema
        elif isinstance(schema, str):
            return value == schema
        else:
            return False

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
    def get_schema() -> Tuple[str, list]:
        """
        获取当前站点模型，只有通用模型需要返回值
        """
        pass

    @staticmethod
    def get_page_source(url: str,
                        ua: str = None,
                        cookies: str = None,
                        proxy: bool = False,
                        render: bool = False,
                        token: str = None,
                        timeout: int = None,
                        referer: str = None,
                        check_code: bool = True) -> str:
        """
        获取页面源码
        :param url: Url地址
        :param ua: User-Agent字符串
        :param cookies: Cookie字符串
        :param proxy: 是否使用代理
        :param render: 是否渲染
        :param token: JWT Token
        :param timeout: 请求超时时间，单位秒
        :param referer: Referer头部信息
        :param check_code: 是否检查 HTTP 返回状态码
        :return: 页面源码，错误信息
        """
        if render:
            return PlaywrightHelper().get_page_source(url=url,
                                                      cookies=cookies,
                                                      ua=ua,
                                                      proxies=settings.PROXY_SERVER if proxy else None,
                                                      timeout=timeout or 60)
        else:
            headers = {}
            if token:
                headers["Authorization"] = token
            if ua:
                headers["User-Agent"] = ua
            if referer:
                headers["Referer"] = referer
            req = RequestUtils(headers=headers,
                               cookies=cookies,
                               proxies=settings.PROXY if proxy else None,
                               timeout=timeout or 20
                               ).get_res(url=url, allow_redirects=False)

            # 重定向
            while req is not None and req.status_code in (301, 302) and req.headers['Location']:
                logger.info(f"重定向 {url} -> {req.headers['Location']}")
                url = urljoin(url, req.headers['Location'])
                req = RequestUtils(headers=headers,
                                   cookies=cookies,
                                   proxies=settings.PROXY if proxy else None,
                                   timeout=timeout or 20
                                   ).get_res(url=url, allow_redirects=False)

            if req is None:
                return ""

            # 403-cloudflare, 468-safeline
            if check_code and req.status_code not in (200, 500, 403, 468):
                return ""

            try:
                if req.content:
                    # 1. 获取编码信息
                    encoding = (RequestUtils.detect_encoding_from_html_response(req,
                                                                                settings.ENCODING_DETECTION_PERFORMANCE_MODE,
                                                                                settings.ENCODING_DETECTION_MIN_CONFIDENCE)
                                or req.apparent_encoding)
                    # 2. 根据解析得到的编码进行解码
                    try:
                        # 尝试用推测的编码解码
                        return req.content.decode(encoding)
                    except Exception as e:
                        logger.debug(f"Decoding failed, error message: {str(e)}")
                        # 如果解码失败，尝试 fallback 使用 apparent_encoding
                        req.encoding = req.apparent_encoding
                        return req.text
                else:
                    return req.text
            except Exception as e:
                logger.debug(f"Error when getting decoded content: {str(e)}")
                return req.text

    @staticmethod
    def test_re(text: str, regexs: list, flags: int = 0) -> bool:
        """
        正则表达式测试
        """
        sub_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", text))
        for regex in regexs:
            if re.search(str(regex), sub_text, flags):
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
