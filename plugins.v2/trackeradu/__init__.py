import operator
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional, Set, Union
from threading import Event as ThreadEvent, RLock
from urllib.parse import urlparse

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from qbittorrentapi.torrents import TorrentDictionary
from transmission_rpc.torrent import Torrent

from app.core.config import settings
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import NotificationType, ServiceInfo


class TrackerADU(_PluginBase):
    # 插件名称
    plugin_name = "Tracker自定义编辑"
    # 插件描述
    plugin_desc = "按照自定义规则批量替换、删除、增加种子tracker"
    # 插件图标
    plugin_icon = "Ittools_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "kim.wu"
    # 作者主页
    author_url = "https://github.com/kimwu2009"
    # 插件配置项ID前缀
    plugin_config_prefix = "trackeradu_"
    # 加载顺序
    plugin_order = 8
    # 可使用的用户级别
    auth_level = 1

    # 常量
    RULE_ADD = "add"
    RULE_DELETE = "del"
    RULE_UPDATE = "rep"

    # 私有属性
    _enabled = False
    _notify = False
    _onlyonce = False
    _cron = None
    _downloaders = None
    _rules = ""

    _dic_rules = {}

    # 私有组件
    # 调度器
    __scheduler: Optional[BackgroundScheduler] = None
    # 下载器帮助类
    __downloader_helper: DownloaderHelper = None
    # 退出事件
    __exit_event: ThreadEvent = ThreadEvent()
    # 任务锁
    __task_lock: RLock = RLock()


    def init_plugin(self, config: dict = None):
        self.__downloader_helper = DownloaderHelper()
        self.__read_config(config)

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self._onlyonce:
            try:
                self.__async_try_run()
                logger.info("立即运行一次成功")
            finally:
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()

        if self.get_state():
            logger.info("插件服务已启用")


    def __read_config(self, config: dict):
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._downloaders = config.get("downloaders")
            self._rules = config.get("rules") or ""


    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "downloaders": self._downloaders,
            "rules": self._rules,
        })


    def __get_new_trackers(self, tracker: str) -> List[str]:
        ret = []
        ori = tracker
        for key in self._dic_rules.keys():
                if key not in tracker:
                    continue
                for parts in self._dic_rules.get(key):
                    op = parts[0].strip().lower()
                    if op == self.RULE_ADD:
                        new_tracker = tracker.replace(parts[1].strip(), parts[2].strip())
                        if new_tracker:
                            # logger.info(f"新增tracker: {tracker} -> {new_tracker}")
                            ret.append(new_tracker)
                    elif op == self.RULE_DELETE:
                        ori = None
                        # logger.info(f"删除tracker: {tracker}")
                    elif op == self.RULE_UPDATE:
                        ori = None
                        new_tracker = tracker.replace(parts[1].strip(), parts[2].strip())
                        if new_tracker:
                            # logger.info(f"替换tracker: {tracker} -> {new_tracker}")
                            ret.append(new_tracker)

        if ori:
            ret.insert(0, ori)
        return ret


    def __get_torrents_for_qbittorrent(self, qbittorrent: Qbittorrent) -> Tuple[List[TorrentDictionary], bool]:
        """
        获取qb种子
        """
        if not qbittorrent:
            return None, False
        return qbittorrent.get_torrents()


    def __update_tracker_for_qbittorrent(self, qbittorrent: Qbittorrent, torrent: TorrentDictionary,
                                          tracker_list: List, new_list: List):
        if not qbittorrent or not qbittorrent.qbc:
            return False

        try:
            toAdd = [x for x in new_list if x not in tracker_list]
            toRemove = [x for x in tracker_list if x not in new_list]
            if len(toAdd) > 0:
                torrent.addTrackers(toAdd)
                # qbittorrent.qbc.torrents_add_trackers(torrent.get("hash"), toAdd)
            if len(toRemove) > 0:
                torrent.removeTrackers(toRemove)
                # qbittorrent.qbc.torrents_remove_trackers(torrent.get("hash"), toRemove)
            if torrent.state_enum.is_uploading:
                torrent.reannounce()
                # qbittorrent.qbc.torrents_reannounce(torrent.get("hash"))
            return True
        except Exception as err:
            logger.warn(f"更新 tracker 出错：hash = {torrent.get('hash')}, name = {torrent.get('name')}, err = {str(err)}")
            return False


    def __handle_torrent_for_qbittorrent(self, qbittorrent: Qbittorrent, torrent: TorrentDictionary):
        if not torrent:
            return
        trackers = [x.url for x in torrent.trackers]
        if not trackers or len(trackers) == 0:
            return

        result = []
        for tracker in trackers:
            result.extend(self.__get_new_trackers(tracker))

        result = list(dict.fromkeys(result))
        if not self.__is_list_equal(trackers, result):
            if self.__update_tracker_for_qbittorrent(qbittorrent=qbittorrent, torrent=torrent,
                                                      tracker_list=trackers, new_list=result):
                logger.info(f"hash = {torrent.get('hash')}, name = {torrent.get('name')}")
                logger.info(f"{trackers}替换为：{result}")


    def __run_for_qbittorrent(self, service_info: ServiceInfo):
        try:
            logger.info(f"下载器[{service_info.name}] - 任务执行开始...")

            if self.__exit_event.is_set():
                logger.warn("插件服务正在退出，任务终止")
                return

            torrents, error = self.__get_torrents_for_qbittorrent(qbittorrent=service_info.instance)
            if error:
                logger.warn(f"下载器[{service_info.name}] - 获取种子失败，任务终止")
                return
            if not torrents or len(torrents) <= 0:
                logger.warn(f"下载器[{service_info.name}] - 没有种子，任务终止")
                return

            for torrent in torrents:
                self.__handle_torrent_for_qbittorrent(qbittorrent=service_info.instance, torrent=torrent)

            logger.info(f"下载器[{service_info.name}] - 任务执行成功")
            self.__send_notification(f"下载器[{service_info.name}] - 任务执行成功")
        except Exception as e:
            logger.error(f"下载器[{service_info.name}] - 任务执行失败: {str(e)}", exc_info=True)


    def __get_torrents_for_transmission(self, transmission: Transmission) -> Tuple[List[Torrent], bool]:
        """
        获取tr种子
        """
        if not transmission:
            return None, False
        return transmission.get_torrents()


    def __update_tracker_for_transmission(self, transmission: Transmission, torrent: Torrent,
                                          tracker_list: List, new_list: List):
        if not transmission or not transmission.trc:
            return False

        try:
            if transmission.get_session().rpc_version >= 17:
                transmission.trc.change_torrent(ids=torrent.hashString, tracker_list=[new_list])
            else:
                urls = [x.announce for x in tracker_list]
                toAdd = [x for x in new_list if x not in urls]
                toRemove = [x.id for x in tracker_list if x.announce not in new_list]
                if len(toAdd) == 0:
                    toAdd = None
                if len(toRemove) == 0:
                    toRemove = None
                if toAdd or toRemove:
                    transmission.trc.change_torrent(ids=torrent.hashString, tracker_add=toAdd, tracker_remove=toRemove)
            if torrent.seeding:
                transmission.trc.reannounce_torrent(ids=torrent.hashString)
            return True
        except Exception as err:
            logger.warn(f"更新 tracker 出错：hash = {torrent.hashString}, name = {torrent.name}, err = {str(err)}")
            return False


    def __handle_torrent_for_transmission(self, transmission: Transmission, torrent: Torrent):
        if not torrent:
            return
        trackers = torrent.trackers
        if not trackers or len(trackers) == 0:
            return

        result = []
        for tracker in trackers:
            result.extend(self.__get_new_trackers(tracker.announce))

        urls = [x.announce for x in trackers]
        result = list(dict.fromkeys(result))
        if not self.__is_list_equal(urls, result):
            if self.__update_tracker_for_transmission(transmission=transmission, torrent=torrent,
                                                      tracker_list=trackers, new_list=result):
                logger.info(f"hash = {torrent.hashString}, name = {torrent.name}")
                logger.info(f"{urls}替换为：{result}")


    def __run_for_transmission(self, service_info: ServiceInfo):
        try:
            logger.info(f"下载器[{service_info.name}] - 任务执行开始...")

            if self.__exit_event.is_set():
                logger.warn("插件服务正在退出，任务终止")
                return

            torrents, error = self.__get_torrents_for_transmission(transmission=service_info.instance)
            if error:
                logger.warn(f"下载器[{service_info.name}] - 获取种子失败，任务终止")
                return
            if not torrents or len(torrents) <= 0:
                logger.warn(f"下载器[{service_info.name}] - 没有种子，任务终止")
                return

            for torrent in torrents:
                self.__handle_torrent_for_transmission(transmission=service_info.instance, torrent=torrent)

            logger.info(f"下载器[{service_info.name}] - 任务执行成功")
            self.__send_notification(f"下载器[{service_info.name}] - 任务执行成功")
        except Exception as e:
            logger.error(f"下载器[{service_info.name}] - 任务执行失败: {str(e)}", exc_info=True)


    def __get_downloader_serviceInfos(self) -> Optional[List[ServiceInfo]]:
        if not self._downloaders:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = self.__downloader_helper.get_services(name_filters=self._downloaders)
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = []
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services.append(service_info)

        if len(active_services) == 0:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services


    def __run_now(self):
        if self.__exit_event.is_set():
            logger.warn("插件服务正在退出，任务终止")
            return

        service_infos = self.__get_downloader_serviceInfos()
        if not service_infos:
            return

        self._dic_rules.clear()
        for line in self._rules.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            count = len(parts)
            if count < 2:
                logger.warn(f"规则配置有误：{line}")
                continue
            op = parts[0].strip().lower()
            key = parts[1].strip()
            if not op or not key:
                logger.warn(f"规则配置有误：{line}")
                continue
            rules = self._dic_rules.get(key, [])
            if op == self.RULE_ADD:
                if count < 3 or not parts[2]:
                    logger.warn(f"规则配置有误：{line}")
                else:
                    rules.append(parts)
                    self._dic_rules[key] = rules
            elif op == self.RULE_DELETE:
                rules.append(parts)
                self._dic_rules[key] = rules
            elif op == self.RULE_UPDATE:
                if count < 3 or not parts[2]:
                    logger.warn(f"规则配置有误：{line}")
                else:
                    rules.append(parts)
                    self._dic_rules[key] = rules
            else:
                logger.warn(f"规则配置有误：{line}")
        
        for service_info in service_infos:
            if service_info.type == "qbittorrent":
                self.__run_for_qbittorrent(service_info=service_info)
            elif service_info.type == "transmission":
                self.__run_for_transmission(service_info=service_info)

        return


    def __start_scheduler(self, timezone=None):
        """
        启动调度器
        :param timezone: 时区
        """
        try:
            scheduler: BackgroundScheduler = self.__scheduler
            if not scheduler:
                if not timezone:
                    timezone = settings.TZ
                self.__scheduler = scheduler = BackgroundScheduler(timezone=timezone)
                logger.debug(f"插件服务调度器初始化完成: timezone = {str(timezone)}")
            if not scheduler.running:
                scheduler.start()
                logger.debug(f"插件服务调度器启动成功")
                scheduler.print_jobs()
        except Exception as e:
            logger.error(f"插件服务调度器启动异常: {str(e)}", exc_info=True)


    def __stop_scheduler(self):
        """
        停止调度器
        """
        try:
            logger.info("尝试停止插件服务调度器...")
            scheduler: BackgroundScheduler = self.__scheduler
            if scheduler:
                scheduler.remove_all_jobs()
                if scheduler.running:
                    scheduler.shutdown()
                self.__scheduler = scheduler = None
                logger.info("插件服务调度器停止成功")
            else:
                logger.info("插件未启用服务调度器，无须停止")
        except Exception as e:
            logger.error(f"插件服务调度器停止异常: {str(e)}", exc_info=True)


    def __try_run(self):
        """
        尝试运行插件任务
        """
        if not self.__task_lock.acquire(blocking=False):
            logger.info("已有进行中的任务，本次不执行")
            return
        try:
            self.__run_now()
        finally:
            self.__task_lock.release()


    def __async_try_run(self):
        """
        异步Try运行
        """
        self.__start_scheduler()
        def __do_task():
            self.__try_run()
        scheduler: BackgroundScheduler = self.__scheduler
        scheduler.add_job(func=__do_task,
                          trigger="date",
                          run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                          name="异步Try运行")


    def __send_notification(self, msg: str):
        """
        发送通知
        :param msg: 通知内容
        """
        if not self._notify or not msg:
            return
        self.post_message(title=f"{self.plugin_name}任务执行结果", text=msg, mtype=NotificationType.Plugin)


    def get_state(self) -> bool:
        return self._enabled


    def get_command() -> List[Dict[str, Any]]:
        pass


    def get_api(self) -> List[Dict[str, Any]]:
        pass


    def get_service(self) -> List[Dict[str, Any]]:
        try:
            if self.get_state() and self._cron:
                return [{
                    "id": f"{self.__class__.__name__}TimerService",
                    "name": f"{self.plugin_name}定时服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.__try_run,
                    "kwargs": {}
                }]
            else:
                return []
        except Exception as e:
            logger.error(f"注册插件公共服务异常: {str(e)}", exc_info=True)


    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                    'md': 4
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
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '定时任务',
                                            'placeholder': '留空不启用定时服务'
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in self.__downloader_helper.get_configs().values()]
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
                                            'model': 'rules',
                                            'label': '编辑规则',
                                            'rows': 5,
                                            'placeholder': f'每行一个规则，支持以下几种编辑规则：\n'
                                                           f'新增：{self.RULE_ADD.upper()}|现有tracker关键字|新增tracker关键字\n'
                                                           f'删除：{self.RULE_DELETE.upper()}|现有tracker关键字\n'
                                                           f'替换：{self.RULE_UPDATE.upper()}|现有tracker关键字|替换tracker关键字'
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
            "onlyonce": False,
            "cron": "0 * * * *",
            "downloaders": [],
            "rules": "",
        }


    def get_page(self) -> List[dict]:
        pass


    def stop_service(self):
        try:
            logger.info("尝试停止插件服务...")
            self.__exit_event.set()
            self.__stop_scheduler()
            logger.info("插件服务停止完成")
        except Exception as e:
            logger.error(f"插件服务停止异常: {str(e)}", exc_info=True)
        finally:
            self.__exit_event.clear()


    def __is_list_equal(self, lst1: List,  lst2: List) -> bool:
        if not lst1 or not lst2 or len(lst1) != len(lst2):
            return False
        return operator.eq(set(lst1), set(lst2))
