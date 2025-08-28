import random
from typing import List, Tuple, Dict, Any, Optional

from qbittorrentapi import TorrentDictionary
from transmission_rpc import Torrent

from app.db.downloadhistory_oper import DownloadHistoryOper, DownloadHistory
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import ServiceInfo


class DownloadHistoryCleaner(_PluginBase):
    # 插件名称
    plugin_name = "下载历史记录清理"
    # 插件描述
    plugin_desc = "删除下载历史记录及下载文件记录，可选删除种子及文件。"
    # 插件图标
    plugin_icon = "clean.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "kim.wu"
    # 作者主页
    author_url = "https://github.com/kimwuX"
    # 插件配置项ID前缀
    plugin_config_prefix = "downloadhistorycleaner_"
    # 加载顺序
    plugin_order = 8
    # 可使用的用户级别
    auth_level = 1

    # 下载历史管理
    __history_oper: DownloadHistoryOper = None

    # 配置属性
    _onlyonce = True
    _delete_torrent = True
    _delete_file = True
    _titles = []
    _episodes = []

    def init_plugin(self, config: dict = None):
        self.__history_oper = DownloadHistoryOper()

        self.__read_config(config)

        # 停止现有任务
        self.stop_service()

        # 立即运行一次
        if self._onlyonce:
            if self._titles or self._episodes:
                self.clean_up()

        self.__update_config()

    def __read_config(self, config: dict):
        if config:
            self._onlyonce = config.get("onlyonce")
            self._delete_torrent = config.get("delete_torrent")
            self._delete_file = config.get("delete_file")
            self._titles = config.get("titles") or []
            self._episodes = config.get("episodes") or []

    def __update_config(self):
        self.update_config({
            "onlyonce": True,
            "delete_torrent": True,
            "delete_file": True,
            "titles": self._titles,
            "episodes": self._episodes,
        })

    def __get_histories(self) -> List[DownloadHistory]:
        res = []
        page = 1
        count = 100
        while True:
            data = self.__history_oper.list_by_page(page = page,
                                                    count = count)
            res.extend(data)
            if len(data) < count:
                break
            page += 1
        return res

    def __delete_history(self, history: DownloadHistory):
        logger.info(f"删除下载历史记录：id={history.id}, "
                    f"title={history.title}{history.seasons}{history.episodes}, "
                    f"hash={history.download_hash}")
        self.__history_oper.delete_history(history.id)

    def __delete_file(self, history: DownloadHistory):
        files = self.__history_oper.get_files_by_hash(history.download_hash)
        for f in files:
            if history.downloader == f.downloader:
                logger.info(f"删除下载文件记录：id={f.id}, "
                            f"hash={f.download_hash}, "
                            f"file={f.filepath}")
                self.__history_oper.delete_downloadfile(f.id)

    def __delete_torrent(self, downloader: ServiceInfo, hashes: set):
        todel = []
        for h in hashes:
            res, _ = downloader.instance.get_torrents(ids=h)
            if res:
                logger.info(f"删除下载器 {downloader.name} 种子：{h}")
                downloader.instance.delete_torrents(delete_file=self._delete_file, ids=h)
                if self._delete_file:
                    todel.extend(res)
            else:
                logger.info(f"下载器 {downloader.name} 不存在种子：{h}")

        # 删除辅种
        if todel:
            self.__delete_related_torrents(downloader, todel)

    def __delete_related_torrents(self, downloader: ServiceInfo, torrents: List):
        if downloader.type not in ["qbittorrent", "transmission"]:
            logger.warn(f"不支持的下载器：{downloader.name}")
            return

        res, _ = downloader.instance.get_torrents()
        for t in torrents:
            logger.debug(f"正在删除下载器 {downloader.name} 辅种："
                         f"{self.__get_value(downloader.type, t, 'name')}...")
            for x in res:
                if not self.__is_same(downloader.type, x, t, "name") or \
                    not self.__is_same(downloader.type, x, t, "total_size"):
                    continue
                if not self.__is_same(downloader.type, x, t, "save_path"):
                    continue
                logger.info(f"删除下载器 {downloader.name} 辅种："
                            f"hash={self.__get_value(downloader.type, x, 'hash')}, "
                            f"name={self.__get_value(downloader.type, x, 'name')}")
                downloader.instance.delete_torrents(delete_file=False,
                                                    ids=self.__get_value(downloader.type, x, "hash"))

    def __get_value(self, type, obj, key):
        '''
        获取 obj 的 key 属性值
        '''
        if key == "hash":
            return obj.get(key) if type == "qbittorrent" else obj.get("hashString")
        elif key == "save_path":
            return obj.get(key) if type == "qbittorrent" else obj.get("downloadDir")
        elif key == "total_size":
            return obj.get(key) if type == "qbittorrent" else obj.get("totalSize")
        return obj.get(key)

    def __is_same(self, type, obj1, obj2, key) -> bool:
        '''
        比较 obj1 和 obj2 的 key 属性值是否相同
        '''
        return self.__get_value(type, obj1, key) == self.__get_value(type, obj2, key)

    def clean_up(self):
        logger.info(f"已选择：{self._titles} {self._episodes}")
        try:
            histories = []
            download_hashes = {}
            for h in self.__get_histories():
                if h.title in self._titles or h.id in self._episodes:
                    histories.append(h)

                    lst = download_hashes.get(h.downloader) or set()
                    lst.add(h.download_hash)
                    download_hashes[h.downloader] = lst

            # 删除下载历史记录
            for h in histories:
                self.__delete_history(h)

            # 删除下载文件记录
            for h in histories:
                self.__delete_file(h)

            # 删除种子
            if self._delete_torrent:
                for key, lst in download_hashes.items():
                    if not lst:
                        continue
                    downloader = self.service_infos.get(key)
                    if not downloader or not downloader.instance:
                        logger.debug(f"下载器 {key} 未连接，跳过")
                        continue
                    self.__delete_torrent(downloader, lst)

            self._titles.clear()
            self._episodes.clear()
        except Exception as e:
            logger.error(f"插件任务异常：{str(e)}", exc_info=True)

    def get_state(self) -> bool:
        return False

    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

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
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        # 标题
        titles = set()
        # 剧集
        episode_options = []
        for h in self.__get_histories():
            titles.add(h.title)

            if h.seasons or h.episodes:
                episode_options.append({"title": f"{h.title} {h.seasons}{h.episodes}",
                                        "value": h.id})

        title_options = [{"title": t, "value": t} for t in titles]

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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'delete_torrent',
                                            'label': '删除种子',
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
                                            'model': 'delete_file',
                                            'label': '删除文件',
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'titles',
                                            'label': '标题',
                                            'items': title_options
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
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'episodes',
                                            'label': '剧集',
                                            'items': episode_options
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                 ]
            }
        ], {
            "onlyonce": True,
            "delete_torrent": True,
            "delete_file": True,
            "titles": [],
            "episodes": []
        }

    def get_page(self) -> List[dict]:
        headers = [
            {'key': 'id', 'title': 'ID'},
            {'key': 'title', 'title': '标题'},
            {'key': 'episode', 'title': '剧集'},
            {'key': 'torrent_site', 'title': '站点'},
            {'key': 'torrent_name', 'title': '种子'}
        ]
        items = [
            {
                'id': data.id,
                'title': data.title,
                'episode': f'{data.seasons}{data.episodes}',
                'torrent_site': data.torrent_site,
                'torrent_name': data.torrent_name
            } for data in self.__get_histories()
        ]
        return [
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
                                'component': 'VDataTableVirtual',
                                'props': {
                                    'headers': headers,
                                    'items': items,
                                    'density': 'compact',
                                    'fixed-header': True,
                                    'hide-no-data': True,
                                    'hover': True
                                }
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        """
        退出插件
        """
        pass

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        services = DownloaderHelper().get_services()
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services
