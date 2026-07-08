import re
import time
from abc import ABCMeta, abstractmethod
from pathlib import Path
from requests import Response
from typing import Any, Tuple
from urllib.parse import urljoin

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.helper.browser import PlaywrightHelper
from app.helper.ocr import OcrHelper
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

    @classmethod
    def get_page_source(cls, url: str,
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
        :return: 页面源码
        """
        # 浏览器仿真
        if render:
            return PlaywrightHelper().get_page_source(url=url,
                                                      cookies=cookies,
                                                      ua=ua,
                                                      proxies=settings.PROXY_SERVER if proxy else None,
                                                      timeout=timeout or 60)

        headers = {}
        if token:
            headers["Authorization"] = token
        if ua:
            headers["User-Agent"] = ua
        if referer:
            headers["Referer"] = referer
        res = RequestUtils(headers=headers,
                           cookies=cookies,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout or 20
                           ).get_res(url=url, allow_redirects=False)

        # 重定向
        while res is not None and res.status_code in (301, 302) and res.headers['Location']:
            logger.info(f"重定向 {url} -> {res.headers['Location']}")
            url = urljoin(url, res.headers['Location'])
            res = RequestUtils(headers=headers,
                               cookies=cookies,
                               proxies=settings.PROXY if proxy else None,
                               timeout=timeout or 20
                               ).get_res(url=url, allow_redirects=False)

        if res is None:
            return ""

        # 403-cloudflare, 468-safeline
        if check_code and res.status_code not in (200, 500, 403, 468):
            return ""

        return cls.decode_response(res)

    @classmethod
    def post_res(cls, url: str,
                 headers: dict = None,
                 ua: str = None,
                 cookies: str = None,
                 proxy: bool = False,
                 timeout: int = None,
                 referer: str = None,
                 data: Any = None,
                 json: dict = None) -> str:
        """
        发送POST请求并返回响应结果
        :param url: Url地址
        :param headers: 请求头部信息，使用 headers 会忽略其它头部参数
        :param ua: User-Agent字符串
        :param cookies: Cookie字符串
        :param proxy: 是否使用代理
        :param timeout: 请求超时时间，单位秒
        :param referer: Referer头部信息
        :param data: 请求的数据
        :param json: 请求的JSON数据
        :return: 响应结果文本
        """
        res = RequestUtils(headers=headers,
                           ua=ua,
                           cookies=cookies,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout,
                           referer=referer
                           ).post_res(url=url, data=data, json=json)

        return cls.decode_response(res)

    @staticmethod
    def decode_response(response: Response) -> str:
        """
        获取 Response 内容
        """
        if response is None:
            return ""
        try:
            if response.content:
                # 1. 获取编码信息
                encoding = (RequestUtils.detect_encoding_from_html_response(response,
                                                                            settings.ENCODING_DETECTION_PERFORMANCE_MODE,
                                                                            settings.ENCODING_DETECTION_MIN_CONFIDENCE)
                            or response.apparent_encoding)
                # 2. 根据解析得到的编码进行解码
                try:
                    # 尝试用推测的编码解码
                    return response.content.decode(encoding)
                except Exception as e:
                    logger.debug(f"Decoding failed, error message: {str(e)}")
                    # 如果解码失败，尝试 fallback 使用 apparent_encoding
                    response.encoding = response.apparent_encoding
                    return response.text
            else:
                return response.text
        except Exception as e:
            logger.debug(f"Error when getting decoded content: {str(e)}")
            return response.text

    @staticmethod
    def img_ocr(site: str = None,
                image_url: str = None,
                image_b64: str = None,
                cookie: str = None,
                ua: str = None,
                length: int = 6,
                max_retry: int = 3) -> str:
        """
        验证码图片识别
        :param site: 站点名称
        :param image_url: 图片地址
        :param image_b64: 图片base64，跳过图片地址下载
        :param cookie: 下载图片使用的cookie
        :param ua: 下载图片使用的ua
        :param length: 验证码长度
        :param max_retry: 最大重试次数
        :return: 验证码识别结果
        """
        result = None
        count = 0
        while count <= max_retry:
            if count > 0:
                # 休眠3s
                time.sleep(3)
                logger.warning(f"{site} 验证码识别失败，正在进行第{count}次重试")
            # ocr二维码识别
            result = OcrHelper().get_captcha_text(image_url=image_url,
                                                  image_b64=image_b64,
                                                  cookie=cookie,
                                                  ua=ua)
            if result:
                if len(result) == length:
                    logger.info(f"{site} 验证码识别成功：{result}")
                    break
                logger.warning(f"{site} 验证码识别错误：{result}")
            count += 1
        return result

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
