import logging
import os
import re
import shutil
from urllib.parse import urlparse

from astrbot.api.all import *

from .core.downloader import BiliDownloader
from .core.rate_limiter import RateLimiter

logger = logging.getLogger("bili_downloader")

# 允许的 B 站域名
BILI_HOSTS = {"bilibili.com", "www.bilibili.com", "b23.tv"}

BILI_REGEX = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9]+(?:[^\s]*)?"
    r"|https?://b23\.tv/[A-Za-z0-9]+(?:[^\s]*)?"
)


@register("bili_downloader", "niniko", "自动解析并下载群内 B 站视频发送到群聊", "2.2.0")
class BiliDownloaderPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

        # ---------- 配置项 ----------
        self.enabled = bool(self.config.get("enabled", True))
        self.bot_self_trigger = bool(self.config.get("bot_self_trigger", True))
        self.group_whitelist = self.config.get("group_whitelist", []) or []
        self.cleanup_temp_on_start = bool(self.config.get("cleanup_temp_on_start", True))

        # ---------- 路径 ----------
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.temp_dir = os.path.join(base_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        if self.cleanup_temp_on_start:
            self._clean_temp_dir()

        # ---------- 核心组件 ----------
        self.downloader = BiliDownloader(self.config, cookie_dir=self.temp_dir)
        self.rate_limiter = RateLimiter(
            cooldown=int(self.config.get("per_user_cooldown", 30)),
            daily_limit=int(self.config.get("per_user_daily_limit", 10)),
        )

    # ===================== 事件入口 =====================

    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.enabled:
            return

        # ---------- 触发条件判断 ----------
        is_self = self._is_self_message(event)
        if is_self:
            if not self.bot_self_trigger:
                return
        else:
            if not getattr(event, "is_at_or_wake_command", False):
                return

        message_str = event.message_str or ""
        match = BILI_REGEX.search(message_str)
        if not match:
            return

        url = match.group(0).rstrip(".,;!?)】」》")
        if not self._is_valid_bili_url(url):
            logger.warning("URL host 不在 B 站白名单内，已忽略: %s", url)
            return

        # ---------- 群白名单 ----------
        if self.group_whitelist:
            gid = str(getattr(event.message_obj, "group_id", "") or "")
            if gid not in [str(g) for g in self.group_whitelist]:
                return

        # ---------- 频率限制 ----------
        user_id = str(getattr(event.message_obj.sender, "user_id", "unknown"))
        ok, reason = self.rate_limiter.check(user_id)
        if not ok:
            yield event.plain_result(reason)
            return

        yield event.plain_result("📥 检测到 B 站视频链接，正在解析并下载中...")

        try:
            file_path, size_mb = await self.downloader.download(url, self.temp_dir)
        except Exception as e:
            logger.exception("下载失败: %s | %s", url, e)
            yield event.plain_result(f"❌ 下载失败: {str(e)[:200]}")
            return

        try:
            # 【关键修复】使用 event.chain_result() 将 list 包装成 AstrBot 能识别的消息链对象
            msg_chain = event.chain_result([
                Plain(f"✨ 视频解析成功（大小: {size_mb:.1f}MB）：\n"),
                Video(file=file_path),
            ])
            await event.send(msg_chain)
        finally:
            self._safe_remove(file_path)

    # ===================== 工具方法 =====================

    @staticmethod
    def _is_self_message(event: AstrMessageEvent) -> bool:
        """判断是否为 bot 自己发出的消息（回环）。"""
        try:
            self_id = str(getattr(event.message_obj, "self_id", "") or "")
            sender_id = str(getattr(event.message_obj.sender, "user_id", "") or "")
            return bool(self_id and sender_id and self_id == sender_id)
        except Exception:
            return False

    @staticmethod
    def _is_valid_bili_url(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()
            return host in BILI_HOSTS
        except Exception:
            return False

    def _safe_remove(self, file_path: str):
        if not file_path:
            return
        try:
            task_dir = os.path.dirname(file_path)
            if os.path.isfile(file_path):
                os.remove(file_path)
            if os.path.isdir(task_dir) and task_dir != self.temp_dir:
                shutil.rmtree(task_dir, ignore_errors=True)
        except Exception:
            logger.warning("清理临时文件失败: %s", file_path, exc_info=True)

    def _clean_temp_dir(self):
        try:
            for name in os.listdir(self.temp_dir):
                path = os.path.join(self.temp_dir, name)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
        except Exception:
            logger.warning("启动清理 temp 目录失败", exc_info=True)