import re
import traceback
from datetime import date, datetime, timedelta
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import ThreadPool
from typing import Any, List, Dict, Tuple, Optional
from urllib.parse import urljoin

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ruamel.yaml import CommentedMap

from app import schemas
from app.chain.site import SiteChain
from app.core.config import settings
from app.core.event import EventManager, eventmanager, Event
from app.db.site_oper import SiteOper
from app.helper.browser import PlaywrightHelper
from app.helper.cloudflare import under_challenge
from app.helper.module import ModuleHelper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.utils.site import SiteUtils
from app.utils.string import StringUtils
from app.utils.timer import TimerUtils


class AutoSignIn(_PluginBase):
    # 插件名称
    plugin_name = "站点自动签到"
    # 插件描述
    plugin_desc = "自动模拟登录、签到站点。"
    # 插件图标
    plugin_icon = "signin.png"
    # 插件版本
    plugin_version = "2.7.0.12"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "autosignin_"
    # 加载顺序
    plugin_order = 0
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    sites: SitesHelper = None
    siteoper: SiteOper = None
    sitechain: SiteChain = None
    # 事件管理器
    event: EventManager = None
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    # 加载的模块
    _site_schema: list = []

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _onlyonce: bool = False
    _notify: bool = False
    _queue_cnt: int = 5
    _sign_sites: list = []
    _login_sites: list = []
    _retry_keyword = None
    _clean: bool = False
    _start_time: int = None
    _end_time: int = None
    _auto_cf: int = 0

    def init_plugin(self, config: dict = None):
        self.sites = SitesHelper()
        self.siteoper = SiteOper()
        self.event = EventManager()
        self.sitechain = SiteChain()

        # 停止现有任务
        self.stop_service()

        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._onlyonce = config.get("onlyonce")
            self._notify = config.get("notify")
            self._queue_cnt = config.get("queue_cnt") or 5
            self._sign_sites = config.get("sign_sites") or []
            self._login_sites = config.get("login_sites") or []
            self._retry_keyword = config.get("retry_keyword")
            self._auto_cf = config.get("auto_cf")
            self._clean = config.get("clean")

            # 过滤掉已删除的站点
            all_sites = [site.id for site in self.siteoper.list_order_by_pri()] + \
                [site.get("id") for site in self.__custom_sites()]
            self._sign_sites = [site_id for site_id in all_sites if site_id in self._sign_sites]
            self._login_sites = [site_id for site_id in all_sites if site_id in self._login_sites]
            # 保存配置
            self.__update_config()

        # 加载模块
        if self._enabled or self._onlyonce:

            self._site_schema = ModuleHelper.load('app.plugins.autosignin.sites',
                                                  filter_func=lambda _, obj: hasattr(obj, 'match'))

            # 立即运行一次
            if self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info("站点自动签到服务启动，立即运行一次")
                self._scheduler.add_job(func=self.sign_in, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="站点自动签到")

                # 关闭一次性开关
                self._onlyonce = False
                # 保存配置
                self.__update_config()

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def __update_config(self):
        # 保存配置
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "cron": self._cron,
                "onlyonce": self._onlyonce,
                "queue_cnt": self._queue_cnt,
                "sign_sites": self._sign_sites,
                "login_sites": self._login_sites,
                "retry_keyword": self._retry_keyword,
                "auto_cf": self._auto_cf,
                "clean": self._clean,
            }
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/site_signin",
            "event": EventType.PluginAction,
            "desc": "站点签到",
            "category": "站点",
            "data": {
                "action": "site_signin"
            }
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        return [{
            "path": "/signin_by_domain",
            "endpoint": self.signin_by_domain,
            "methods": ["GET"],
            "summary": "站点签到",
            "description": "使用站点域名签到站点",
        }]

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        try:
            if self._enabled:
                if self._cron:
                    return [{
                        "id": "AutoSignIn",
                        "name": "站点自动签到服务",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "func": self.sign_in,
                        "kwargs": {}
                    }]
                else:
                    # 随机两次执行时间
                    triggers = TimerUtils.random_scheduler(num_executions=2,
                                                        begin_hour=9,
                                                        end_hour=23,
                                                        max_interval=6 * 60,
                                                        min_interval=2 * 60)
                    logger.debug(f"随机时间：{[f"{trigger.hour}时{trigger.minute}分" for trigger in triggers]}")
                    cron_list = [str(triggers[0].minute), str(triggers[0].hour), "*", "*", "*"]
                    for i in range(1, len(triggers)):
                        cron_list[1] += f",{triggers[i].hour}"
                    logger.info("签到周期：" + " ".join(cron_list))
                    return [{
                        "id": "AutoSignIn",
                        "name": "站点自动签到服务",
                        "trigger": CronTrigger.from_crontab(" ".join(cron_list)),
                        "func": self.sign_in,
                        "kwargs": {}
                    }]
        except Exception as err:
            logger.error(f"定时任务配置错误：{str(err)}")
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 站点的可选项（内置站点 + 自定义站点）
        customSites = self.__custom_sites()

        site_options = ([{"title": site.name, "value": site.id}
                         for site in self.siteoper.list_order_by_pri()]
                        + [{"title": site.get("name"), "value": site.get("id")}
                           for site in customSites])
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clean',
                                            'label': '清理本日缓存',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'queue_cnt',
                                            'label': '队列数量'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'retry_keyword',
                                            'label': '重试关键词',
                                            'placeholder': '支持正则表达式，命中才重签'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'auto_cf',
                                            'label': '自动优选',
                                            'placeholder': '命中重试关键词次数（0-关闭）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'clearable': True,
                                            'model': 'sign_sites',
                                            'label': '签到站点',
                                            'items': site_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'clearable': True,
                                            'model': 'login_sites',
                                            'label': '登录站点',
                                            'items': site_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '执行周期支持：'
                                                    '1、5位cron表达式；'
                                                    '2、配置间隔（小时），如2.3/9-23（9-23点之间每隔2.3小时执行一次）；'
                                                    '3、周期不填默认9-23点随机执行2次。'
                                                    '每天首次全量执行，其余执行命中重试关键词的站点。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '自动优选：0-关闭，命中重试关键词次数大于该数量时自动执行Cloudflare IP优选（需要开启且则正确配置Cloudflare IP优选插件和自定义Hosts插件）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '不是所有的站点都会把程序自动登录/签到定义为用户活跃（比如馒头），提示签到/登录成功仍然存在掉号风险！请结合站点公告说明自行把握。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "cron": "",
            "auto_cf": 0,
            "onlyonce": False,
            "clean": False,
            "queue_cnt": 5,
            "sign_sites": [],
            "login_sites": [],
            "retry_keyword": "错误|失败"
        }

    def __custom_sites(self) -> List[Any]:
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites")
        return custom_sites

    def __get_plugin_data(self, pkey, ckey):
        res = self.get_data(pkey)
        return res.get(ckey) if res else None

    def __set_plugin_data(self, pkey, ckey, value):
        res = self.get_data(pkey)
        if res is None:
            res = {}
        res[ckey] = value
        self.save_data(pkey, res)

    def __clean_history_data(self, type_str: str, days: int):
        today = datetime.now().date()
        delta = timedelta(days=days)
        re_record = r"(\d+)月(\d+)日"
        re_site = r"(\d+)-(\d+)-(\d+)"

        # 删除 record 数据
        record = self.get_data("record") or {}
        logger.debug(f"record处理前：{record}")
        keys = list(record.keys())
        for key in keys:
            res = re.search(re_record, key)
            if not res:
                continue
            temp = date(year=today.year, month=int(res.group(1)), day=int(res.group(2)))
            if temp > today:
                temp = date(year=today.year - 1, month=int(res.group(1)), day=int(res.group(2)))
            if today - temp < delta:
                continue
            items = record.get(key) or []
            tokeep = []
            while len(items) > 0:
                item = items.pop(0)
                if item.get("status") and type_str in item.get("status"):
                    continue
                tokeep.append(item)
            if len(tokeep) > 0:
                record[key] = tokeep
            else:
                logger.debug(f"删除 {key} 数据")
                del record[key]
        logger.debug(f"record处理后：{record}")
        self.save_data("record", record)

        # 删除 site 数据
        site = self.get_data("site") or {}
        logger.debug(f"site处理前：{site}")
        keys = list(site.keys())
        for key in keys:
            if type_str not in key:
                continue
            res = re.search(re_site, key)
            if not res:
                continue
            temp = date(year=int(res.group(1)), month=int(res.group(2)), day=int(res.group(3)))
            if today - temp < delta:
                continue
            logger.debug(f"删除 {key} 数据")
            del site[key]
        logger.debug(f"site处理后：{site}")
        self.save_data("site", site)

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 获取最近14天的日期数组
        date_list = [(datetime.now() - timedelta(days=i)).date() for i in range(14)]

        # 获取所有数据，包括签到和登录历史
        all_data = {
            "signin": [],  # 签到数据
            "login": []  # 登录数据
        }
        sign_dates = set()
        sites_info = {}  # 记录站点信息

        # 获取站点信息
        for site in self.siteoper.list_order_by_pri():
            sites_info[site.id] = site.name

        # 自定义站点
        custom_sites = self.__custom_sites()
        for site in custom_sites:
            sites_info[site.get("id")] = site.get("name")

        # 获取常规日期格式数据
        for day in date_list:
            day_str = f"{day.month}月{day.day}日"
            day_formatted = day.strftime('%Y-%m-%d')

            # 获取"月日"格式数据
            day_data = self.__get_plugin_data(pkey="record", ckey=day_str)
            if day_data:
                # 添加日期信息到每条记录
                if isinstance(day_data, list):
                    for record in day_data:
                        if isinstance(record, dict):
                            record["date"] = day_str
                            record["day_obj"] = day
                            # 区分签到和登录数据
                            if "登录" in record.get("status", ""):
                                all_data["login"].append(record)
                            else:
                                all_data["signin"].append(record)
                    sign_dates.add(day_str)

            """
            # 获取"签到-yyyy-mm-dd"和"登录-yyyy-mm-dd"格式数据
            signin_history = self.__get_plugin_data(pkey="site", ckey=f"签到-{day_formatted}")
            if signin_history:
                if isinstance(signin_history, dict):
                    # 获取完成签到的站点ID列表
                    done_sites = signin_history.get("do", [])
                    retry_sites = signin_history.get("retry", [])

                    # 为所有已完成签到的站点创建记录
                    for site_id in done_sites:
                        site_id_str = str(site_id)
                        site_name = sites_info.get(site_id_str) or sites_info.get(site_id) or f"站点ID: {site_id}"

                        # 跳过需要重试的站点
                        if site_id in retry_sites:
                            # 为需要重试的站点添加记录
                            status_text = "需要重试"
                            all_data["signin"].append({
                                "site": site_name,
                                "status": status_text,
                                "date": day_str,
                                "day_obj": day,
                                "site_id": site_id
                            })
                        else:
                            # 为已完成的站点添加记录
                            status_text = "已签到"
                            all_data["signin"].append({
                                "site": site_name,
                                "status": status_text,
                                "date": day_str,
                                "day_obj": day,
                                "site_id": site_id
                            })

                    sign_dates.add(day_str)

            # 获取登录历史数据
            login_history = self.__get_plugin_data(pkey="site", ckey=f"登录-{day_formatted}")
            if login_history:
                if isinstance(login_history, dict):
                    # 获取完成登录的站点ID列表
                    done_sites = login_history.get("do", [])
                    retry_sites = login_history.get("retry", [])

                    # 为所有已完成登录的站点创建记录
                    for site_id in done_sites:
                        site_id_str = str(site_id)
                        site_name = sites_info.get(site_id_str) or sites_info.get(site_id) or f"站点ID: {site_id}"

                        # 跳过需要重试的站点
                        if site_id in retry_sites:
                            # 为需要重试的站点添加记录
                            status_text = "需要重试"
                            all_data["login"].append({
                                "site": site_name,
                                "status": status_text,
                                "date": day_str,
                                "day_obj": day,
                                "site_id": site_id
                            })
                        else:
                            # 为已完成的站点添加记录
                            status_text = "登录成功"
                            all_data["login"].append({
                                "site": site_name,
                                "status": status_text,
                                "date": day_str,
                                "day_obj": day,
                                "site_id": site_id
                            })

                    sign_dates.add(day_str)
            """

        # 如果没有数据，显示提示信息
        if not all_data["signin"] and not all_data["login"]:
            return [{
                'component': 'VAlert',
                'props': {
                    'type': 'info',
                    'text': '暂无签到数据',
                    'variant': 'tonal',
                    'class': 'mt-4',
                    'prepend-icon': 'mdi-information'
                }
            }]

        # 确保签到数据中至少有所有日期的记录
        if sign_dates:
            sign_dates_list = list(sign_dates)
            sign_dates_list.sort(reverse=True)  # 最新日期优先
        else:
            sign_dates_list = [f"{date_list[0].month}月{date_list[0].day}日"]

        # 按站点分组并去重数据
        signin_site_data = {}
        login_site_data = {}

        # 处理签到数据 - 每个站点每天只保留一条最新记录
        site_day_records = {}  # 用于去重: {site}_{date} -> record
        for data in all_data["signin"]:
            site_name = data.get("site", "未知站点")
            date_str = data.get("date", "")
            site_day_key = f"{site_name}_{date_str}"

            # 存储或更新记录（如有多条取最新）
            site_day_records[site_day_key] = data

        # 整理去重后的数据
        for key, record in site_day_records.items():
            site_name = record.get("site", "未知站点")
            if site_name not in signin_site_data:
                signin_site_data[site_name] = []
            signin_site_data[site_name].append(record)

        # 处理登录数据 - 同样去重
        site_day_records = {}  # 重置去重字典
        for data in all_data["login"]:
            site_name = data.get("site", "未知站点")
            date_str = data.get("date", "")
            site_day_key = f"{site_name}_{date_str}"

            # 存储或更新记录
            site_day_records[site_day_key] = data

        # 整理去重后的数据
        for key, record in site_day_records.items():
            site_name = record.get("site", "未知站点")
            if site_name not in login_site_data:
                login_site_data[site_name] = []
            login_site_data[site_name].append(record)

        # 创建签到折叠面板
        signin_panels = []
        for site_name, records in signin_site_data.items():
            # 按日期排序，最新的在前面
            try:
                records.sort(key=lambda x: x.get("day_obj", datetime.now().date()), reverse=True)
            except:
                pass  # 排序失败时跳过

            # 获取最新的状态作为站点概要
            latest_status = records[0].get("status", "未知状态")

            # 确定状态颜色和图标
            status_color = "teal-lighten-3"
            status_icon = "mdi-emoticon-happy-outline"

            if "失败" in latest_status or "错误" in latest_status:
                status_color = "deep-orange-lighten-3"
                status_icon = "mdi-emoticon-sad-outline"
            elif "Cookie已失效" in latest_status:
                status_color = "pink-lighten-3"
                status_icon = "mdi-cookie-off"
            elif "重试" in latest_status:
                status_color = "amber-lighten-3"
                status_icon = "mdi-emoticon-confused-outline"
            elif "已签到" in latest_status:
                status_color = "light-blue-lighten-3"
                status_icon = "mdi-emoticon-cool-outline"
            elif "成功" in latest_status:
                status_color = "teal-lighten-3"
                status_icon = "mdi-emoticon-happy-outline"

            # 创建每个站点的折叠面板
            signin_panels.append(
                self._create_expansion_panel(site_name, records, status_color, status_icon, latest_status))

        # 创建登录折叠面板
        login_panels = []
        for site_name, records in login_site_data.items():
            # 按日期排序，最新的在前面
            try:
                records.sort(key=lambda x: x.get("day_obj", datetime.now().date()), reverse=True)
            except:
                pass  # 排序失败时跳过

            # 获取最新的状态作为站点概要
            latest_status = records[0].get("status", "未知状态")

            # 确定状态颜色和图标
            status_color = "teal-lighten-3"
            status_icon = "mdi-emoticon-happy-outline"

            if "失败" in latest_status or "错误" in latest_status:
                status_color = "deep-orange-lighten-3"
                status_icon = "mdi-emoticon-sad-outline"
            elif "Cookie已失效" in latest_status:
                status_color = "pink-lighten-3"
                status_icon = "mdi-cookie-off"
            elif "重试" in latest_status:
                status_color = "amber-lighten-3"
                status_icon = "mdi-emoticon-confused-outline"
            elif "已签到" in latest_status:
                status_color = "light-blue-lighten-3"
                status_icon = "mdi-emoticon-cool-outline"
            elif "成功" in latest_status:
                status_color = "teal-lighten-3"
                status_icon = "mdi-emoticon-happy-outline"

            # 创建每个站点的折叠面板
            login_panels.append(
                self._create_expansion_panel(site_name, records, status_color, status_icon, latest_status))

        # 添加样式
        return [
            {
                'component': 'style',
                'text': """
                .v-expansion-panel-title {
                    min-height: 48px !important;
                    padding: 0 16px !important;
                }
                .v-expansion-panel-text__wrapper {
                    padding: 0 !important;
                }
                .v-expansion-panel {

                    margin-bottom: 10px !important;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                    border-radius: 16px !important;
                    overflow: hidden !important;
                    border: 1px solid rgba(0,0,0,0.03);
                    transition: all 0.3s ease;
                }
                .v-expansion-panel:hover {

                    box-shadow: 0 4px 12px rgba(0,0,0,0.08) !important;
                    transform: translateY(-2px);
                }
                .site-item {
                    border-radius: 10px;
                    transition: all 0.3s ease;
                    margin: 5px 0;

                }
                .site-item:hover {

                    transform: scale(1.01);
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                }
                .text-teal-lighten-3 {
                    color: #80CBC4 !important;
                }
                .text-deep-orange-lighten-3 {
                    color: #FFAB91 !important;
                }
                .text-pink-lighten-3 {
                    color: #F8BBD0 !important;
                }
                .text-amber-lighten-3 {
                    color: #FFE082 !important;
                }
                .text-light-blue-lighten-3 {
                    color: #81D4FA !important;
                }
                .status-icon {
                    width: 24px;
                    height: 24px;
                    line-height: 24px;
                    text-align: center;
                    border-radius: 50%;
                    margin-right: 8px;
                }
                .signin-card, .login-card {
                    transition: all 0.3s ease;
                    border-radius: 20px !important;
                    overflow: hidden;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.03) !important;
                    border: 1px solid rgba(0,0,0,0.03);
                }
                .signin-card:hover, .login-card:hover {
                    transform: translateY(-3px);
                    box-shadow: 0 6px 20px rgba(0,0,0,0.05) !important;
                }
                .v-card-title.gradient-title {
                    margin-bottom: 0 !important;
                    border-bottom: 1px solid rgba(0,0,0,0.03);
                }
                .signin-card .v-card-title.gradient-title {
                    background: linear-gradient(135deg, rgba(128, 203, 196, 0.15) 0%, rgba(165, 214, 167, 0.15) 100%);
                }
                .login-card .v-card-title.gradient-title {
                    background: linear-gradient(135deg, rgba(129, 212, 250, 0.15) 0%, rgba(159, 168, 218, 0.15) 100%);
                }
                .date-chip {
                    margin: 2px !important;
                    border-radius: 14px !important;
                    font-size: 0.75rem !important;
                }
                .status-chip {
                    padding: 0 8px;
                    border-radius: 14px !important;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.03);
                }
                .site-icon {
                    background: linear-gradient(45deg, #80CBC4, #81D4FA);
                    color: white !important;
                    border-radius: 12px;
                    width: 32px;
                    height: 32px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-right: 10px;
                    font-weight: bold;
                    font-size: 15px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.06);
                }
                .page-title {
                    font-size: 1.5rem;
                    font-weight: 600;
                    background: -webkit-linear-gradient(45deg, #80CBC4, #81D4FA);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                }
                """
            },
            {
                'component': 'VRow',
                'props': {
                    'class': 'mt-2'
                },
                'content': [
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'class': 'pb-0'
                        },
                        'content': [
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'd-flex align-center mb-4'
                                },
                                'content': [
                                    {
                                        'component': 'VIcon',
                                        'props': {
                                            'color': 'light-blue-lighten-3',
                                            'class': 'mr-2',
                                            'size': 'large',
                                            'icon': 'mdi-cat'
                                        }
                                    },
                                    {
                                        'component': 'h2',
                                        'props': {
                                            'class': 'page-title m-0'
                                        },
                                        'text': '站点签到小助手'
                                    },
                                    {
                                        'component': 'VSpacer'
                                    },
                                    {
                                        'component': 'VChip',
                                        'props': {
                                            'color': 'light-blue-lighten-5',
                                            'size': 'small',
                                            'variant': 'elevated',
                                            'class': 'ml-2',
                                            'prepend-icon': 'mdi-paw'
                                        },
                                        'text': f'显示 {len(sign_dates_list)} 天数据'
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                'component': 'VRow',
                'content': [
                    # 左侧 - 签到数据
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'flat',
                                    'class': 'mb-4 signin-card'
                                },
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'gradient-title d-flex align-center pa-4'
                                        },
                                        'content': [
                                            {
                                                'component': 'VIcon',
                                                'props': {
                                                    'class': 'mr-2',
                                                    'color': 'teal-lighten-3',
                                                    'size': 'small',
                                                    'icon': 'mdi-duck'
                                                }
                                            },
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'font-weight-medium'
                                                },
                                                'text': '签到打卡记录'
                                            },
                                            {
                                                'component': 'VSpacer'
                                            },
                                            {
                                                'component': 'VChip',
                                                'props': {
                                                    'color': 'teal-lighten-5',
                                                    'size': 'x-small',
                                                    'variant': 'elevated',
                                                    'class': 'ml-2',
                                                    'prepend-icon': 'mdi-rabbit'
                                                },
                                                'text': f'{len(signin_site_data)} 个站点'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'pa-3'
                                        },
                                        'content': [
                                            {
                                                'component': 'VExpansionPanels',
                                                'props': {
                                                    'variant': 'accordion',
                                                    'class': 'mt-2'
                                                },
                                                'content': signin_panels or [{
                                                    'component': 'VAlert',
                                                    'props': {
                                                        'type': 'info',
                                                        'text': '暂无签到数据',
                                                        'variant': 'tonal',
                                                        'class': 'mt-2',
                                                        'density': 'compact',
                                                        'prepend-icon': 'mdi-penguin'
                                                    }
                                                }]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # 右侧 - 登录数据
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'flat',
                                    'class': 'mb-4 login-card'
                                },
                                'content': [
                                    {
                                        'component': 'VCardTitle',
                                        'props': {
                                            'class': 'gradient-title d-flex align-center pa-4'
                                        },
                                        'content': [
                                            {
                                                'component': 'VIcon',
                                                'props': {
                                                    'class': 'mr-2',
                                                    'color': 'light-blue-accent-3',
                                                    'size': 'small',
                                                    'icon': 'mdi-dog'
                                                }
                                            },
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'font-weight-medium'
                                                },
                                                'text': '登录记录'
                                            },
                                            {
                                                'component': 'VSpacer'
                                            },
                                            {
                                                'component': 'VChip',
                                                'props': {
                                                    'color': 'light-blue-lighten-4',
                                                    'size': 'x-small',
                                                    'variant': 'elevated',
                                                    'class': 'ml-2',
                                                    'prepend-icon': 'mdi-panda'
                                                },
                                                'text': f'{len(login_site_data)} 个站点'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'pa-3'
                                        },
                                        'content': [
                                            {
                                                'component': 'VExpansionPanels',
                                                'props': {
                                                    'variant': 'accordion',
                                                    'class': 'mt-2'
                                                },
                                                'content': login_panels or [{
                                                    'component': 'VAlert',
                                                    'props': {
                                                        'type': 'info',
                                                        'text': '暂无登录数据',
                                                        'variant': 'tonal',
                                                        'class': 'mt-2',
                                                        'density': 'compact',
                                                        'prepend-icon': 'mdi-cat'
                                                    }
                                                }]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def _create_expansion_panel(self, site_name, records, status_color, status_icon, latest_status):
        """创建站点折叠面板"""
        # 生成站点图标（使用站点名的首字母）
        site_initial = site_name[0].upper() if site_name else "?"

        # 生成记录列表
        records_list = []
        for record in records:
            date_str = record.get("date", "")
            status_text = record.get("status", "未知状态")

            # 确定状态颜色和图标
            record_color = "success"
            record_icon = "mdi-check-circle"

            if "失败" in status_text or "错误" in status_text:
                record_color = "error"
                record_icon = "mdi-alert-circle"
            elif "Cookie已失效" in status_text:
                record_color = "error"
                record_icon = "mdi-cookie-off"
            elif "重试" in status_text:
                record_color = "warning"
                record_icon = "mdi-refresh"
            elif "已签到" in status_text:
                record_color = "info"
                record_icon = "mdi-check"
            elif "登录成功" in status_text:
                record_color = "success"
                record_icon = "mdi-login-variant"

            # 创建记录项
            records_list.append({
                'component': 'VListItem',
                'props': {
                    'class': 'site-item px-2 py-1'
                },
                'content': [
                    {
                        'component': 'div',
                        'props': {
                            'class': 'd-flex align-center w-100'
                        },
                        'content': [
                            {
                                'component': 'VChip',
                                'props': {
                                    'color': 'grey-lighten-3',
                                    'size': 'x-small',
                                    'class': 'date-chip mr-2',
                                    'variant': 'flat',
                                    'prepend-icon': 'mdi-flower-tulip'
                                },
                                'text': date_str
                            },
                            {
                                'component': 'VSpacer'
                            },
                            {
                                'component': 'VChip',
                                'props': {
                                    'color': record_color,
                                    'size': 'x-small',
                                    'class': 'ml-2 status-chip',
                                    'variant': 'flat',
                                    'prepend-icon': record_icon
                                },
                                'text': status_text
                            }
                        ]
                    }
                ]
            })

        # 创建折叠面板
        return {
            'component': 'VExpansionPanel',
            'content': [
                {
                    'component': 'VExpansionPanelTitle',
                    'content': [{
                        'component': 'div',
                        'props': {
                            'class': 'd-flex align-center'
                        },
                        'content': [
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'site-icon'
                                },
                                'text': site_initial
                            },
                            {
                                'component': 'span',
                                'props': {
                                    'class': 'font-weight-medium'
                                },
                                'text': site_name
                            },
                            {
                                'component': 'VSpacer'
                            },
                            {
                                'component': 'VIcon',
                                'props': {
                                    'color': status_color,
                                    'class': 'mr-2',
                                    'size': 'small'
                                },
                                'text': status_icon
                            },
                            {
                                'component': 'span',
                                'props': {
                                    'class': f'text-{status_color} text-caption'
                                },
                                'text': latest_status
                            }
                        ]
                    }]
                },
                {
                    'component': 'VExpansionPanelText',
                    'content': [
                        {
                            'component': 'VList',
                            'props': {
                                'lines': 'one',
                                'density': 'compact'
                            },
                            'content': records_list
                        }
                    ]
                }
            ]
        }

    @eventmanager.register(EventType.PluginAction)
    def sign_in(self, event: Event = None):
        """
        自动签到|模拟登录
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "site_signin":
                return
        # 日期
        today = datetime.today()
        if self._start_time and self._end_time:
            if int(datetime.today().hour) < self._start_time or int(datetime.today().hour) > self._end_time:
                logger.error(
                    f"当前时间 {int(datetime.today().hour)} 不在 {self._start_time}-{self._end_time} 范围内，暂不执行任务")
                return
        if event:
            logger.info("收到命令，开始站点签到 ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始站点签到 ...",
                              userid=event.event_data.get("user"))

        # 删除旧数据
        for row in self.get_data():
            if row and row.key not in ["record", "site"]:
                logger.debug(f"删除：{row.key}")
                self.del_data(row.key)

        if self._sign_sites:
            self.__do(today=today, type_str="签到", do_sites=self._sign_sites, event=event)
        if self._login_sites:
            self.__do(today=today, type_str="登录", do_sites=self._login_sites, event=event)

    def __do(self, today: datetime, type_str: str, do_sites: list, event: Event = None):
        """
        签到逻辑
        """
        # 删除历史记录
        self.__clean_history_data(type_str=type_str, days=3)

        # 查看今天有没有签到|登录历史
        today = today.strftime('%Y-%m-%d')
        today_history = self.__get_plugin_data(pkey="site", ckey=f"{type_str}-{today}")

        # 查询所有站点
        all_sites = [site for site in self.sites.get_indexers() if not site.get("public")] + self.__custom_sites()
        # 过滤掉没有选中的站点
        if do_sites:
            do_sites = [site for site in all_sites if site.get("id") in do_sites]
        else:
            do_sites = all_sites

        # 今日没数据
        if not today_history or self._clean:
            logger.info(f"今日 {today} 未{type_str}，开始{type_str}已选站点")
            if self._clean:
                # 关闭开关
                self._clean = False
        else:
            # 需要重试站点
            retry_sites = today_history.get("retry") or []
            # 今天已签到|登录站点
            already_sites = today_history.get("do") or []

            # 今日未签|登录站点
            no_sites = [site for site in do_sites if
                        site.get("id") not in already_sites or site.get("id") in retry_sites]

            if not no_sites:
                logger.info(f"今日 {today} 已{type_str}，无重新{type_str}站点，本次任务结束")
                return

            # 任务站点 = 需要重试+今日未do
            do_sites = no_sites
            logger.info(f"今日 {today} 已{type_str}，开始重试命中关键词站点")

        if not do_sites:
            logger.info(f"没有需要{type_str}的站点")
            return

        # 执行签到
        logger.info(f"开始执行{type_str}任务 ...")
        if type_str == "签到":
            with ThreadPool(min(len(do_sites), int(self._queue_cnt))) as p:
                status = p.map(self.signin_site, do_sites)
        else:
            with ThreadPool(min(len(do_sites), int(self._queue_cnt))) as p:
                status = p.map(self.login_site, do_sites)

        if status:
            logger.info(f"站点{type_str}任务完成！")
            # 获取今天的日期
            key = f"{datetime.now().month}月{datetime.now().day}日"
            today_data = self.__get_plugin_data(pkey="record", ckey=key)
            if today_data:
                if not isinstance(today_data, list):
                    today_data = [today_data]
                for s in status:
                    today_data.append({
                        "site": s[0],
                        "status": s[1]
                    })
            else:
                today_data = [{
                    "site": s[0],
                    "status": s[1]
                } for s in status]
            # 保存数据
            self.__set_plugin_data(pkey="record", ckey=key, value=today_data)

            # 命中重试词的站点id
            retry_sites = []
            # 命中重试词的站点签到msg
            retry_msg = []
            # 登录成功
            login_success_msg = []
            # 签到成功
            sign_success_msg = []
            # 已签到
            already_sign_msg = []
            # 仿真签到成功
            fz_sign_msg = []
            # 失败｜错误
            failed_msg = []

            sites = {site.get('name'): site.get("id") for site in self.sites.get_indexers() if not site.get("public")}
            for s in status:
                site_name = s[0]
                site_id = None
                if site_name:
                    site_id = sites.get(site_name)

                if 'Cookie已失效' in str(s) and site_id:
                    # 触发自动登录插件登录
                    logger.info(f"触发站点 {site_name} 自动登录更新Cookie和UA")
                    self.eventmanager.send_event(EventType.PluginAction,
                                                 {
                                                     "site_id": site_id,
                                                     "action": "site_refresh"
                                                 })
                # 记录本次命中重试关键词的站点
                if self._retry_keyword:
                    if site_id:
                        match = re.search(self._retry_keyword, s[1])
                        if match:
                            logger.debug(f"站点 {site_name} 命中重试关键词 {self._retry_keyword}")
                            retry_sites.append(site_id)
                            # 命中的站点
                            retry_msg.append(s)
                            continue

                if "登录成功" in str(s):
                    login_success_msg.append(s)
                elif "仿真签到成功" in str(s):
                    fz_sign_msg.append(s)
                    continue
                elif "签到成功" in str(s):
                    sign_success_msg.append(s)
                elif '已签到' in str(s):
                    already_sign_msg.append(s)
                else:
                    failed_msg.append(s)

            if not self._retry_keyword:
                # 没设置重试关键词则重试已选站点
                retry_sites = self._sign_sites if type_str == "签到" else self._login_sites
            logger.debug(f"下次{type_str}重试站点 {retry_sites}")

            # 存入历史
            self.__set_plugin_data(pkey="site", ckey=f"{type_str}-{today}",
                                   value={
                                       "do": self._sign_sites if type_str == "签到" else self._login_sites,
                                       "retry": retry_sites
                                   })

            # 自动Cloudflare IP优选
            if self._auto_cf and int(self._auto_cf) > 0 and retry_msg and len(retry_msg) >= int(self._auto_cf):
                self.eventmanager.send_event(EventType.PluginAction, {
                    "action": "cloudflare_speedtest"
                })

            # 发送通知
            if self._notify:
                # 签到详细信息 登录成功、签到成功、已签到、仿真签到成功、失败--命中重试
                signin_message = login_success_msg + sign_success_msg + already_sign_msg + fz_sign_msg + failed_msg
                if len(retry_msg) > 0:
                    signin_message += retry_msg

                signin_message = "\n".join([f'【{s[0]}】{s[1]}' for s in signin_message if s])
                self.post_message(title=f"【站点自动{type_str}】",
                                  mtype=NotificationType.SiteMessage,
                                  text=f"全部{type_str}数量: {len(self._sign_sites if type_str == '签到' else self._login_sites)} \n"
                                       f"本次{type_str}数量: {len(do_sites)} \n"
                                       f"下次{type_str}数量: {len(retry_sites) if self._retry_keyword else 0} \n"
                                       f"{signin_message}"
                                  )
            if event:
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"站点{type_str}完成！", userid=event.event_data.get("user"))
        else:
            logger.error(f"站点{type_str}任务失败！")
            if event:
                self.post_message(channel=event.event_data.get("channel"),
                                  title=f"站点{type_str}任务失败！", userid=event.event_data.get("user"))
        # 保存配置
        self.__update_config()

    def __build_class(self, url) -> Any:
        for site_schema in self._site_schema:
            try:
                if site_schema.match(url):
                    return site_schema
            except Exception as e:
                logger.error("站点模块加载失败：%s" % str(e))
        return None

    def signin_by_domain(self, url: str, apikey: str) -> schemas.Response:
        """
        签到一个站点，可由API调用
        """
        # 校验
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        domain = StringUtils.get_url_domain(url)
        site_info = self.sites.get_indexer(domain)
        if not site_info:
            return schemas.Response(
                success=True,
                message=f"站点【{url}】不存在"
            )
        else:
            site_name, message = self.signin_site(site_info)
            return schemas.Response(
                success=True,
                message=f"站点【{site_name}】{message or '签到成功'}"
            )

    def signin_site(self, site_info: CommentedMap) -> Tuple[str, str]:
        """
        签到一个站点
        """
        site_module = self.__build_class(site_info.get("url"))
        # 开始记时
        start_time = datetime.now()
        if site_module and hasattr(site_module, "signin"):
            try:
                state, message = site_module().signin(site_info)
            except Exception as e:
                traceback.print_exc()
                state, message = False, f"签到失败：{str(e)}"
        else:
            state, message = AutoSignIn.__signin_base(site_info)
        # 统计
        seconds = (datetime.now() - start_time).seconds
        domain = StringUtils.get_url_domain(site_info.get('url'))
        if state:
            self.siteoper.success(domain=domain, seconds=seconds)
        else:
            self.siteoper.fail(domain)
        return site_info.get("name"), message

    @staticmethod
    def __signin_base(site_info: CommentedMap) -> Tuple[bool, str]:
        """
        通用签到处理
        :param site_info: 站点信息
        :return: 签到结果信息
        """
        if not site_info:
            return False, ""
        site = site_info.get("name")
        site_url = site_info.get("url")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        render = site_info.get("render")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        if not site_url or not site_cookie:
            logger.warn(f"未配置 {site} 的站点地址或Cookie，无法签到")
            return False, ""

        # cloudflare challenge
        re_cf = [r'cf-turnstile']

        # safeline firewall
        re_sl = [r'slg-title', r'slg-box', r'sl-box']

        # other chanllenges
        re_ch = [r'dragContainer', r'dragBg', r'dragText', r'dragHandler']

        # 已签到
        # 您今天已经签到过了，请勿重复刷新。
        re_signed = [r'您今天已经签到过了，请勿重复刷新']

        # 签到成功
        # 这是您的第233次签到，已连续签到233天，本次签到获得1000个憨豆。
        # 这是您的第 <b>233</b> 次签到，已连续签到 <b>233</b> 天，本次签到获得 <b>233</b> 个啤酒瓶。
        # 這是您的第 <b>233</b> 次簽到，已連續簽到 <b>233</b> 天，本次簽到獲得 <b>233</b> 個魔力值。
        re_success = [r'连续签到\s*\S*?\d+\S*?\s*天，本次签到获得',
                      r'連續簽到\s*\S*?\d+\S*?\s*天，本次簽到獲得']

        # 模拟签到
        try:
            # 签到地址
            checkin_url = urljoin(site_url, "/attendance.php")
            logger.info(f"开始签到 {site}，地址：{checkin_url}")
            html_text = AutoSignIn.get_page_source(url=checkin_url,
                                            cookie=site_cookie,
                                            ua=ua,
                                            proxy=proxy,
                                            render=render,
                                            timeout=timeout)

            if not html_text:
                logger.warn(f"{site} 签到失败，请检查站点连通性")
                return False, '签到失败，请检查站点连通性'

            if under_challenge(html_text):
                logger.warn(f"{site} 签到失败，无法绕过Cloudflare检测")
                return False, '签到失败，无法绕过Cloudflare检测'

            for regex in re_sl:
                if re.search(regex, html_text):
                    logger.warn(f"{site} 签到失败，无法绕过雷池检测")
                    return False, '签到失败，无法绕过雷池检测'

            for regex in re_ch:
                if re.search(regex, html_text):
                    logger.warn(f"{site} 签到失败，无法通过验证")
                    return False, '签到失败，无法通过验证'

            if not SiteUtils.is_logged_in(html_text):
                logger.warn(f"{site} 签到失败，Cookie已失效")
                return False, '签到失败，Cookie已失效'

            for regex in re_cf:
                if re.search(regex, html_text):
                    logger.warn(f"{site} 签到失败，签到页面已被Cloudflare防护")
                    return False, '签到失败，签到页面已被Cloudflare防护'

            if "take2fa.php" in html_text:
                logger.warn(f"{site} 签到失败，两步验证拦截")
                return False, '签到失败，两步验证拦截'

            # 已签到
            for regex in re_signed:
                if re.search(regex, html_text):
                    logger.info(f"{site} 今日已签到")
                    return True, '今日已签到'

            # 签到成功
            for regex in re_success:
                if re.search(regex, html_text):
                    logger.info(f"{site} 签到成功")
                    return True, '签到成功'

            logger.warn(f"{site} 签到失败，接口返回：\n{html_text}")
            return False, '签到失败，请查看日志'
        except Exception as e:
            traceback.print_exc()
            logger.warn(f"{site} 签到失败，错误信息：\n{str(e)}")
            return False, '签到失败，未知错误'

    def login_site(self, site_info: CommentedMap) -> Tuple[str, str]:
        """
        模拟登录一个站点
        """
        site_module = self.__build_class(site_info.get("url"))
        # 开始记时
        start_time = datetime.now()
        if site_module and hasattr(site_module, "login"):
            try:
                state, message = site_module().login(site_info)
            except Exception as e:
                traceback.print_exc()
                state, message = False, f"模拟登录失败：{str(e)}"
        else:
            state, message = AutoSignIn.__login_base(site_info)
        # 统计
        seconds = (datetime.now() - start_time).seconds
        domain = StringUtils.get_url_domain(site_info.get('url'))
        if state:
            self.siteoper.success(domain=domain, seconds=seconds)
        else:
            self.siteoper.fail(domain)
        return site_info.get("name"), message

    @staticmethod
    def __login_base(site_info: CommentedMap) -> Tuple[bool, str]:
        """
        模拟登录通用处理
        :param site_info: 站点信息
        :return: 模拟登录结果信息
        """
        if not site_info:
            return False, ""
        site = site_info.get("name")
        site_url = site_info.get("url")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        render = site_info.get("render")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        if not site_url or not site_cookie:
            logger.warn(f"未配置 {site} 的站点地址或Cookie，无法模拟登录")
            return False, ""

        # safeline firewall
        re_sl = [r'slg-title', r'slg-box', r'sl-box']

        # 模拟登录
        try:
            logger.info(f"开始模拟登录 {site}，地址：{site_url}")
            html_text = AutoSignIn.get_page_source(url=site_url,
                                            cookie=site_cookie,
                                            ua=ua,
                                            proxy=proxy,
                                            render=render,
                                            timeout=timeout)

            if not html_text:
                logger.warn(f"{site} 模拟登录失败，请检查站点连通性")
                return False, '模拟登录失败，请检查站点连通性'

            if under_challenge(html_text):
                logger.warn(f"{site} 模拟登录失败，无法绕过Cloudflare检测")
                return False, '模拟登录失败，无法绕过Cloudflare检测'

            for regex in re_sl:
                if re.search(regex, html_text):
                    logger.warn(f"{site} 模拟登录失败，无法绕过雷池检测")
                    return False, '模拟登录失败，无法绕过雷池检测'

            if not SiteUtils.is_logged_in(html_text):
                logger.warn(f"{site} 模拟登录失败，Cookie已失效")
                return False, '模拟登录失败，Cookie已失效'

            logger.info(f"{site} 模拟登录成功")
            return True, '模拟登录成功'
        except Exception as e:
            traceback.print_exc()
            logger.warn(f"{site} 模拟登录失败，错误信息：\n{str(e)}")
            return False, '模拟登录失败，未知错误'

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

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    @eventmanager.register(EventType.SiteDeleted)
    def site_deleted(self, event):
        """
        删除对应站点选中
        """
        site_id = event.event_data.get("site_id")
        config = self.get_config()
        if config:
            self._sign_sites = self.__remove_site_id(config.get("sign_sites") or [], site_id)
            self._login_sites = self.__remove_site_id(config.get("login_sites") or [], site_id)
            # 保存配置
            self.__update_config()

    def __remove_site_id(self, do_sites, site_id):
        if do_sites:
            if isinstance(do_sites, str):
                do_sites = [do_sites]

            # 删除对应站点
            if site_id:
                do_sites = [site for site in do_sites if int(site) != int(site_id)]
            else:
                # 清空
                do_sites = []

            # 若无站点，则停止
            if len(do_sites) == 0:
                self._enabled = False

        return do_sites


def record_to_row(record):
    """辅助函数：将记录转换为表格行"""
    status = record.get("status", "")

    # 确定状态图标和颜色
    icon = "mdi-check-circle"
    color = "success"

    if "失败" in status or "错误" in status:
        icon = "mdi-alert-circle"
        color = "error"
    elif "Cookie已失效" in status:
        icon = "mdi-cookie-off"
        color = "error"
    elif "已签到" in status:
        icon = "mdi-check"
        color = "grey"
    elif "成功" in status:
        icon = "mdi-check-circle"
        color = "success"

    return {
        'component': 'tr',
        'props': {
            'class': 'text-sm'
        },
        'content': [
            {
                'component': 'td',
                'props': {
                    'class': 'text-start'
                },
                'text': record.get("date", "")
            },
            {
                'component': 'td',
                'props': {
                    'class': 'text-start'
                },
                'text': status
            },
            {
                'component': 'td',
                'props': {
                    'class': 'text-center'
                },
                'content': [
                    {
                        'component': 'VIcon',
                        'props': {
                            'color': color,
                            'size': 'small'
                        },
                        'text': icon
                    }
                ]
            }
        ]
    }
