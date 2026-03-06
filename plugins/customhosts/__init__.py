from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from python_hosts import Hosts, HostsEntry

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.ip import IpUtils
from app.utils.system import SystemUtils


class CustomHosts(_PluginBase):
    # 插件名称
    plugin_name = "自定义Hosts"
    # 插件描述
    plugin_desc = "修改系统hosts文件，加速网络访问。"
    # 插件图标
    plugin_icon = "hosts.png"
    # 插件版本
    plugin_version = "1.2.2"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "customhosts_"
    # 加载顺序
    plugin_order = 10
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _notify = False
    _hosts = ""
    _err_hosts = ""

    _hosts_list = []
    _scheduler = None

    _comment_text = "# CustomHostsPlugin"

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._hosts = config.get("hosts")
            self._err_hosts = config.get("err_hosts")

            self._hosts_list = self._hosts.split("\n") if self._hosts else []

        # 立即运行一次
        try:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info(f"服务启动，立即运行一次")
            self._scheduler.add_job(func=self.__run_now, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3))

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
        except Exception as e:
            logger.error(f"立即运行一次异常：{str(e)}", exc_info=True)

    def __update_config(self):
        self._hosts = '\n'.join(self._hosts_list)
        self.update_config({
            "hosts": self._hosts,
            "notify": self._notify,
            "err_hosts": self._err_hosts,
            "enabled": self._enabled
        })

    def __run_now(self):
        if self._enabled and self._hosts_list:
            # 添加到系统
            self.__add_hosts_to_system()
        else:
            # hosts为空或未启用，清除系统hosts
            self.__clear_system_hosts()

    @staticmethod
    def __read_system_hosts():
        """
        读取系统hosts对象
        """
        # 获取本机hosts路径
        if SystemUtils.is_windows():
            hosts_path = r"c:\windows\system32\drivers\etc\hosts"
        else:
            hosts_path = '/etc/hosts'
        # 读取系统hosts
        return Hosts(path=hosts_path)

    def __clear_system_hosts(self):
        """
        清除系统hosts
        """
        # 系统hosts对象
        system_hosts = self.__read_system_hosts()
        # 过滤掉插件添加的hosts
        orgin_entries = []
        for entry in system_hosts.entries:
            if entry.entry_type == "comment" and entry.comment == self._comment_text:
                break
            orgin_entries.append(entry)

        if len(system_hosts.entries) == len(orgin_entries):
            logger.debug("系统 hosts 无变化，无需恢复")
            return

        system_hosts.entries = orgin_entries
        try:
            system_hosts.write()
            logger.info("系统 hosts 文件已恢复")
        except Exception as err:
            logger.error(f"恢复系统 hosts 文件失败：{str(err) or '请检查权限'}")
            if self._notify:
                self.post_message(mtype=NotificationType.Plugin,
                                  title=f"【{self.plugin_name}】插件",
                                  text=f"恢复系统 hosts 文件失败：{str(err) or '请检查权限'}")

    def __add_hosts_to_system(self):
        """
        添加hosts到系统
        """
        # 系统hosts对象
        system_hosts = self.__read_system_hosts()
        # 过滤掉插件添加的hosts
        orgin_entries = []
        for entry in system_hosts.entries:
            if entry.entry_type == "comment" and entry.comment == self._comment_text:
                break
            orgin_entries.append(entry)
        system_hosts.entries = orgin_entries

        # 有效hosts
        new_entrys = []
        # 错误的hosts
        err_hosts = []
        for host in self._hosts_list:
            if not host or not host.strip():  # 空行
                continue
            host = host.strip()
            if host.startswith('#'):  # 注释行
                host_entry = HostsEntry(entry_type='comment', comment=host)
                new_entrys.append(host_entry)
                continue

            try:
                host_arr = host.split()
                host_entry = HostsEntry(entry_type='ipv4' if IpUtils.is_ipv4(str(host_arr[0])) else 'ipv6',
                                        address=host_arr[0], names=host_arr[1:])
                new_entrys.append(host_entry)
            except Exception:
                err_hosts.append(host)
                logger.warning(f"格式转换错误：{host}")

        # 写入系统hosts
        try:
            if new_entrys:
                # 添加分隔标识
                system_hosts.add([HostsEntry(entry_type='comment', comment=self._comment_text)])
                # 添加新的Hosts
                system_hosts.add(new_entrys, allow_address_duplication=True)
                system_hosts.write()
                logger.info("更新系统 hosts 文件成功")
        except Exception as err:
            self._enabled = False
            logger.error(f"更新系统 hosts 文件失败：{str(err) or '请检查权限'}")
            if self._notify:
                self.post_message(mtype=NotificationType.Plugin,
                                  title=f"【{self.plugin_name}】插件",
                                  text=f"更新系统 hosts 文件失败：{str(err) or '请检查权限'}")

        self._err_hosts = ", ".join(err_hosts)
        self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/custom_hosts_cfip",
            "event": EventType.PluginAction,
            "desc": "自定义Hosts 更新优选 IP",
            "data": {
                "action": "custom_hosts_cfip"
            }
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                    'md': 6
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
                                    'md': 4
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
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'hosts',
                                            'label': '自定义hosts',
                                            'rows': 10,
                                            'placeholder': '每行一个配置，格式为：ip host1 host2 ...'
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'err_hosts',
                                            'readonly': True,
                                            'label': '错误hosts',
                                            'rows': 2,
                                            'placeholder': '错误的hosts配置会展示在此处，请修改上方hosts重新提交（错误的hosts不会写入系统hosts文件）'
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
                                            'text': 'host格式ip host，中间有空格！！！'
                                                    '（注：容器运行则更新容器hosts！非宿主机！）'
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
            "notify": False,
            "hosts": "",
            "err_hosts": ""
        }

    def get_page(self) -> List[dict]:
        pass

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

    @eventmanager.register(EventType.PluginAction)
    def event_handler(self, event: Event):
        """
        远程命令处理
        """
        event_data = event.event_data
        if not event_data or event_data.get("action") != "custom_hosts_cfip":
            return
        ip_o = event_data.get("ip_o")
        ip_n = event_data.get("ip_n")
        logger.info(f"收到命令，开始更新优选 IP: [{ip_o}] => [{ip_n}] ...")
        if not ip_o or not IpUtils.is_ip(ip_o) or not ip_n or not IpUtils.is_ip(ip_n):
            logger.warning(f"IP 地址格式有误: 旧({ip_o}) / 新({ip_n})，退出更新流程")
            return

        if self._notify:
            self.post_message(channel=event.event_data.get("channel"),
                              title=f"【{self.plugin_name}】插件",
                              text="开始更新优选 IP ...",
                              userid=event.event_data.get("user"))

        # 处理ip
        for i in range(len(self._hosts_list)):
            host = self._hosts_list[i]
            if not host or not host.strip():
                continue
            # comment
            if host.strip().startswith("#"):
                continue
            if host.strip().split()[0] == ip_o:
                self._hosts_list[i] = host.replace(ip_o, ip_n)

        self.__update_config()
        self.__run_now()

        if self._notify:
            self.post_message(channel=event.event_data.get("channel"),
                              title=f"【{self.plugin_name}】插件",
                              text="更新优选 IP 任务结束",
                              userid=event.event_data.get("user"))
