import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any
from threading import Event as ThreadEvent, RLock

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.core.plugin import PluginManager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils
from app.utils.ip import IpUtils
from app.utils.system import SystemUtils


class CloudflareSpeedTest(_PluginBase):
    # 插件名称
    plugin_name = "Cloudflare IP优选"
    # 插件描述
    plugin_desc = "🌩 测试 Cloudflare CDN 延迟和速度，自动优选IP。"
    # 插件图标
    plugin_icon = "cloudflare.jpg"
    # 插件版本
    plugin_version = "1.5.3"
    # 插件作者
    plugin_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    plugin_config_prefix = "cloudflarespeedtest_"
    # 加载顺序
    plugin_order = 12
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _cf_ip = None
    _scheduler = None
    _cron = None
    _onlyonce = False
    _ipv4 = False
    _ipv6 = False
    _version = None
    _additional_args = None
    _re_install = False
    _notify = False
    _check = False
    _cf_path = None
    _cf_ipv4 = None
    _cf_ipv6 = None
    _result_file = None
    _release_api = 'https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest'
    _release_prefix = 'https://github.com/XIU2/CloudflareSpeedTest/releases/download'
    _binary_name = 'cfst'

    # 退出事件
    __exit_event: ThreadEvent = None
    # 任务锁
    __task_lock: RLock = None

    def init_plugin(self, config: dict = None):
        self.__exit_event = ThreadEvent()
        self.__task_lock = RLock()
        # 停止现有任务
        self.stop_service()

        # 读取配置
        if config:
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._cf_ip = config.get("cf_ip")
            self._version = config.get("version")
            self._ipv4 = config.get("ipv4")
            self._ipv6 = config.get("ipv6")
            self._re_install = config.get("re_install")
            self._additional_args = config.get("additional_args")
            self._notify = config.get("notify")
            self._check = config.get("check")

        if self._onlyonce:
            try:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"服务启动，立即运行一次")
                self._scheduler.add_job(func=self.try_run, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3))

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()
            except Exception as e:
                logger.error(f"立即运行一次异常：{str(e)}", exc_info=True)
            finally:
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()

    def try_run(self):
        """
        尝试运行插件任务
        """
        if not self.__task_lock.acquire(blocking=False):
            logger.warning("已有进行中的任务，本次不执行")
            return
        try:
            self.__cloudflareSpeedTest()
        except Exception as e:
            logger.error(f"尝试运行插件任务异常：{str(e)}", exc_info=True)
        finally:
            self.__task_lock.release()

    def __cloudflareSpeedTest(self):
        """
        CloudflareSpeedTest优选
        """
        if self.__exit_event.is_set():
            logger.warning("插件服务正在退出，任务终止")
            return

        self._cf_path = self.get_data_path().joinpath('app')
        self._cf_ipv4 = "ip.txt"
        self._cf_ipv6 = "ipv6.txt"
        self._result_file = "result.txt"

        if not PluginManager.is_plugin_exists("CustomHosts"):
            logger.error(f"当前插件依赖于【自定义Hosts】插件，请先安装并配置【自定义Hosts】")
            return

        if SystemUtils.is_windows():
            self._binary_name = "cfst.exe"
        else:
            self._binary_name = "cfst"

        # ipv4和ipv6必须其一
        if not self._ipv4 and not self._ipv6:
            self._ipv4 = True
            self.__update_config()
            logger.warning(f"未指定 IP 类型，默认为 IPv4")

        flag, release_version = self.__check_environment()
        if not flag:
            return
        if release_version:
            # 更新版本
            self._version = release_version
            self.__update_config()
        if self.__exit_event.is_set():
            logger.warning("插件服务正在退出，任务终止")
            return

        if self._ipv4 and not self._cf_path.joinpath(self._cf_ipv4).exists():
            logger.error(f"数据文件 {self._cf_ipv4} 丢失，请打开【重装后运行】开关重试")
            return

        if self._ipv6 and not self._cf_path.joinpath(self._cf_ipv6).exists():
            logger.error(f"数据文件 {self._cf_ipv6} 丢失，请打开【重装后运行】开关重试")
            return

        # 校正优选ip
        if self._check:
            self.__check_cf_ip()

        # 开始优选
        logger.info("正在进行 IP 优选测试，请耐心等待 ...")
        # 执行优选命令，-dd不测速
        if SystemUtils.is_windows():
            cf_command = f'cd \"{self._cf_path}\" && {self._binary_name} ' + (
                f'{self._additional_args} -p 0 -o \"{self._result_file}\"') + (
                f' -f \"{self._cf_ipv4}\"' if self._ipv4 else '') + (
                f' -f \"{self._cf_ipv6}\"' if self._ipv6 else '')
        else:
            cf_command = f'cd {self._cf_path} && chmod a+x {self._binary_name} && ./{self._binary_name} ' + (
                f'{self._additional_args} -p 0 -o {self._result_file}') + (
                f' -f {self._cf_ipv4}' if self._ipv4 else '') + (
                f' -f {self._cf_ipv6}' if self._ipv6 else '')
        logger.debug(f'优选命令: {cf_command}')
        try:
            subprocess.run(cf_command, shell=True, check=True, timeout=600)
        except Exception as e:
            logger.error(f'优选测试失败: {e}')
            self.__kill_process(self._binary_name)
            return
        if self.__exit_event.is_set():
            logger.warning("插件服务正在退出，任务终止")
            return

        # 获取优选后最优ip
        try:
            with open(self._cf_path.joinpath(self._result_file), 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if lines and len(lines) > 1:
                best_ip = lines[1].split(',')[0]
        except Exception as e:
            logger.warning(f'获取优选结果失败: {e}')
        if not best_ip:
            logger.error("未能获取新优选 IP，停止运行")
            return

        logger.info(f"新优选 IP 获取成功: {best_ip}")
        if best_ip == self._cf_ip:
            logger.info(f"优选 IP 未改变，不做处理")
            return

        # 通知自定义Hosts插件更新hosts
        if IpUtils.is_ip(best_ip):
            # 更新优选ip
            old_ip = self._cf_ip
            self._cf_ip = best_ip
            self.__update_config()

            # 触发【自定义Hosts】插件更新操作
            logger.info("通知【自定义Hosts】插件更新系统 hosts 文件...")
            self.eventmanager.send_event(EventType.PluginAction,
                                         {
                                             "action": "custom_hosts_cfip",
                                             "ip_o": old_ip,
                                             "ip_n": best_ip
                                         })
            if self._notify:
                self.post_message(mtype=NotificationType.Plugin,
                                  title=f"【{self.plugin_name}】插件",
                                  text=f"原 IP: " + (old_ip if old_ip else "未配置") + f"\n新 IP: {best_ip}")

    def __check_cf_ip(self):
        """
        校正cf优选ip
        防止特殊情况下cf优选ip和【自定义Hosts】插件中ip不一致
        """
        customHosts = self.get_config("CustomHosts")
        if not customHosts:
            logger.warning("获取【自定义Hosts】配置失败，无法自动校准")
            return
        hosts = customHosts.get("hosts")
        if isinstance(hosts, str):
            hosts_list = hosts.split('\n')
        if not hosts_list:
            logger.warning("【自定义Hosts】参数配置为空，无法自动校准")
            return

        # 统计每个IP地址出现的次数
        ip_count = {}
        for host in hosts_list:
            if not host or not host.strip():  # 空行
                continue
            host = host.strip()
            if host.startswith('#'):  # 注释行
                continue
            ip = host.split()[0]
            if ip in ip_count:
                ip_count[ip] += 1
            else:
                ip_count[ip] = 1

        # 找出出现次数最多的IP地址
        max_ips = []  # 保存最多出现的IP地址
        max_count = 0
        for ip, count in ip_count.items():
            if count > max_count:
                max_ips = [ip]  # 更新最多的IP地址
                max_count = count
            elif count == max_count:
                max_ips.append(ip)

        # 如果出现次数最多的ip不止一个，则不做兼容处理
        if len(max_ips) != 1:
            return

        if IpUtils.is_ip(max_ips[0]) and not IpUtils.is_private_ip(max_ips[0]) and max_ips[0] != self._cf_ip:
            self._cf_ip = max_ips[0]
            self.__update_config()
            logger.info(f"检测到【自定义hosts】插件中 [{max_ips[0]}] 出现次数最多，已自动校正当前优选 IP")

    def __check_environment(self):
        """
        环境检查
        """
        # 是否安装标识
        install_flag = False

        # 是否重新安装
        if self._re_install:
            install_flag = True
            if not self.__remove_file_or_dir(self._cf_path):
                logger.error(f'App 目录删除失败')
                return False, None
            self._re_install = False
            self.__update_config()
            logger.info(f'已删除 App 目录({self._cf_path})，开始重新安装')

        # 判断目录是否存在
        if not self._cf_path.exists():
            self._cf_path.mkdir(parents=True)

        # 获取CloudflareSpeedTest最新版本
        release_version = self.__get_release_version()
        if not release_version:
            # 如果升级失败但是有可执行文件，则可继续运行，反之停止
            if self._cf_path.joinpath(self._binary_name).exists():
                logger.warning(f"获取 App 版本失败，存在可执行版本，继续运行")
                return True, None
            elif self._version:
                logger.warning(f"获取 App 版本失败，开始安装上次运行版本({self._version})")
                install_flag = True
            else:
                release_version = "v2.3.4"
                self._version = release_version
                logger.warning(f"获取 App 版本失败，开始安装默认版本({release_version})")
                install_flag = True

        # 有更新
        if not install_flag and release_version != self._version:
            logger.info(f"检测到 App 有版本更新，开始安装: {release_version}")
            install_flag = True

        # 重装后数据库有版本数据，但是本地没有则重装
        if not install_flag and release_version == self._version \
            and not self._cf_path.joinpath(self._binary_name).exists():
            logger.warning(f"未检测到可执行文件，开始重新安装: {release_version}")
            install_flag = True

        if not install_flag:
            logger.info(f"App 无版本更新，继续运行")
            return True, None

        # 检查环境、安装
        if SystemUtils.is_windows():
            # windows
            cf_file_name = 'cfst_windows_amd64.zip'
            # https://github.com/XIU2/CloudflareSpeedTest/releases/download/v2.3.4/cfst_windows_amd64.zip
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            command = ""
        elif SystemUtils.is_macos():
            # mac
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'cfst_darwin_{arch}.zip'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            command = f"ditto -V -x -k --sequesterRsrc {self._cf_path.joinpath(cf_file_name)} {self._cf_path}"
        else:
            # linux
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'cfst_linux_{arch}.tar.gz'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            command = f"tar -zxf {self._cf_path.joinpath(cf_file_name)} -C {self._cf_path}"
        return self.__os_install(download_url, cf_file_name, release_version, command)

    def __os_install(self, download_url, cf_file_name, release_version, unzip_command):
        """
        安装CloudflareSpeedTest
        """
        binary_path = self._cf_path.joinpath(self._binary_name)
        cf_file_path = self._cf_path.joinpath(cf_file_name)
        # 手动下载安装包后，无需在此下载
        if not cf_file_path.exists():
            # 首次下载或下载新版压缩包
            self.__get_cloudflare_st(download_url, cf_file_path)

        # 判断是否下载好安装包
        if cf_file_path.exists():
            try:
                # 解压
                if SystemUtils.is_windows():
                    with zipfile.ZipFile(cf_file_path, 'r') as zip_ref:
                        # 解压ZIP文件中的所有文件到指定目录
                        zip_ref.extractall(self._cf_path)
                else:
                    subprocess.run(unzip_command, shell=True, check=True)

                if binary_path.exists():
                    logger.info(f"App 安装成功，当前版本: {release_version}")
                    # 删除压缩包
                    self.__remove_file_or_dir(cf_file_path)
                    return True, release_version
                else:
                    logger.error(f"App 安装失败，未检测到可执行文件，停止运行")
                    return False, None
            except Exception as err:
                logger.warning(f"App 解压失败: {str(err)}")
                # 如果升级失败但是有可执行文件，则可继续运行，反之停止
                if binary_path.exists():
                    logger.warning(f"App 解压失败，存在可执行版本，继续运行")
                    return True, None
                else:
                    logger.error(f"App 解压失败，无可用版本，停止运行")
                    return False, None
        else:
            # 如果下载升级失败但是有可执行文件，则可继续运行，反之停止
            if binary_path.exists():
                logger.warning(f"App 下载失败，存在可执行版本，继续运行")
                return True, None
            else:
                logger.error(f"App 下载失败，无可用版本，停止运行")
                return False, None

    def __get_cloudflare_st(self, download_url, cf_file_path):
        try:
            response = RequestUtils(proxies=settings.PROXY).get_res(url=download_url, stream=True)
            if response is None:
                logger.warning(f"App 下载失败: 网络连接失败")
            elif response.status_code == 200:
                with open(cf_file_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)
                logger.info(f"App 下载成功")
            else:
                logger.warning(f"App 下载失败: {response.status_code} {response.reason}")
        except Exception as e:
            logger.warning(f"App 下载失败: {str(e)}")

    def __get_release_version(self):
        """
        获取CloudflareSpeedTest最新版本
        """
        version_res = RequestUtils(proxies=settings.PROXY).get_res(self._release_api)
        if version_res:
            ver_json = version_res.json()
            version = f"{ver_json['tag_name']}"
            return version
        else:
            return None

    @staticmethod
    def __kill_process(process_name):
        try:
            if SystemUtils.is_windows():
                # Windows系统使用taskkill命令
                subprocess.run(['taskkill', '/F', '/IM', process_name], check=True)
            else:
                # Linux/macOS系统使用pkill命令
                subprocess.run(['pkill', '-f', process_name], check=True)
        except Exception as e:
            logger.error(f"终止进程发生错误: {e}")

    @staticmethod
    def __remove_file_or_dir(path):
        try:
            if os.path.isfile(path) or os.path.islink(path):
                # 删除文件或符号链接
                os.unlink(path)
            elif os.path.isdir(path):
                # 删除目录及其所有内容
                shutil.rmtree(path)
            else:
                logger.warning(f"路径不存在: {path}")
            return True
        except PermissionError:
            logger.warning(f"权限不足，无法删除: {path}")
        except Exception as e:
            logger.warning(f"{path} 删除失败: {e}")
        return False

    def __update_config(self):
        """
        更新优选插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "cf_ip": self._cf_ip,
            "version": self._version,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "re_install": self._re_install,
            "additional_args": self._additional_args,
            "notify": self._notify,
            "check": self._check
        })

    def get_state(self) -> bool:
        return True if self._cron else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/cloudflare_speedtest",
            "event": EventType.PluginAction,
            "desc": "Cloudflare IP优选",
            "data": {
                "action": "cloudflare_speedtest"
            }
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/cloudflare_speedtest",
            "endpoint": self.cloudflare_speedtest_api,
            "methods": ["GET"],
            "summary": "Cloudflare IP优选",
            "description": "Cloudflare IP优选",
        }]

    def get_service(self) -> List[Dict[str, Any]]:
        try:
            if self.get_state():
                return [{
                    "id": f"{self.__class__.__name__}TimerService",
                    "name": f"{self.plugin_name}定时服务",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.try_run,
                    "kwargs": {}
                }]
        except Exception as e:
            logger.error(f"注册插件公共服务异常：{str(e)}", exc_info=True)
        return []

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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cf_ip',
                                            'label': '优选IP',
                                            'placeholder': '121.121.121.121'
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
                                        'component': 'VCronField',
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'version',
                                            'readonly': True,
                                            'label': 'CloudflareSpeedTest版本',
                                            'placeholder': '暂未安装'
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ipv4',
                                            'label': 'IPv4',
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
                                            'model': 'ipv6',
                                            'label': 'IPv6',
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
                                            'model': 'check',
                                            'label': '自动校准',
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
                                            'model': 're_install',
                                            'label': '重装后运行',
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'additional_args',
                                            'label': '高级参数',
                                            'placeholder': '-dd'
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
                                            'text': 'F12看请求的Server属性，如果是cloudflare说明该站点支持Cloudflare IP优选。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "cf_ip": "",
            "cron": "",
            "version": "",
            "ipv4": True,
            "ipv6": False,
            "check": False,
            "onlyonce": False,
            "re_install": False,
            "notify": False,
            "additional_args": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            self.__exit_event.set()
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
        finally:
            self.__exit_event.clear()

    def cloudflare_speedtest_api(self, apikey: str) -> schemas.Response:
        """
        API调用CloudflareSpeedTest IP优选
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        self.try_run()
        return schemas.Response(success=True)

    @eventmanager.register(EventType.PluginAction)
    def event_handler(self, event: Event):
        """
        远程命令处理
        """
        event_data = event.event_data
        if not event_data or event_data.get("action") != "cloudflare_speedtest":
            return

        logger.info(f"收到命令，开始优选 IP 测试 ...")
        if self._notify:
            self.post_message(channel=event.event_data.get("channel"),
                              title=f"【{self.plugin_name}】插件",
                              text="开始优选 IP 测试 ...",
                              userid=event.event_data.get("user"))

        self.try_run()

        if self._notify:
            self.post_message(channel=event.event_data.get("channel"),
                              title=f"【{self.plugin_name}】插件",
                              text=f"优选 IP 测试结束",
                              userid=event.event_data.get("user"))
