"""风控对抗模块：匿名获取 buvid 指纹、请求头伪装、代理、Cookies 加载。

本模块不涉及任何账号登录，仅通过 B 站公开接口获取匿名设备指纹
（buvid3 / buvid4 / buvid_fp / b_nut）并配合完整的浏览器请求头伪装，
以降低匿名下载时的 412 / 403 风控概率。
"""

import hashlib
import logging
import os
import time
import uuid
from typing import Optional

import requests

logger = logging.getLogger("bili_downloader.anti_risk")

# buvid 指纹缓存有效期（12 小时）
BUVID_CACHE_TTL = 12 * 3600

# B 站指纹接口
FINGER_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"


class AntiRiskManager:
    """封装所有请求伪装手段，供 downloader 使用。"""

    def __init__(self, config: dict, cookie_dir: str):
        self.config = config
        self.cookie_dir = cookie_dir
        os.makedirs(self.cookie_dir, exist_ok=True)

        # ---------- 用户配置 ----------
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.proxy_url = (config.get("proxy_url") or "").strip()
        self.use_anon_buvid = bool(config.get("use_anonymous_buvid", True))
        self.custom_cookie_file = (config.get("cookie_file") or "").strip()

        # ---------- 匿名 cookie 文件 ----------
        self._anon_cookie_path = os.path.join(self.cookie_dir, "anon_cookies.txt")

        # 从已有文件的 mtime 恢复时间戳，让 TTL 跨重启生效
        self._buvid_fetched_at: float = 0.0
        if os.path.isfile(self._anon_cookie_path):
            try:
                self._buvid_fetched_at = os.path.getmtime(self._anon_cookie_path)
            except OSError:
                self._buvid_fetched_at = 0.0

    # ===================== 对外接口 =====================

    def apply_to_opts(self, ydl_opts: dict) -> dict:
        """将风控对抗措施注入 yt-dlp 配置。"""
        # 1. 完整浏览器请求头（Origin / Referer 对 B 站 API 是硬性要求）
        ydl_opts["http_headers"] = {
            "User-Agent": self.user_agent,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # 2. Cookies 文件
        cookie_path = self._resolve_cookie_file()
        if cookie_path:
            ydl_opts["cookiefile"] = cookie_path
            logger.info("使用 cookies 文件: %s", cookie_path)
        else:
            logger.warning("未获取到任何 cookies，可能因 B 站风控导致下载失败")

        # 3. 代理
        if self.proxy_url:
            ydl_opts["proxy"] = self.proxy_url
            logger.info("使用代理: %s", self.proxy_url)

        return ydl_opts

    # ===================== Cookies 处理 =====================

    def _resolve_cookie_file(self) -> Optional[str]:
        """优先用户自定义 cookie，其次使用匿名 buvid cookie。"""
        if self.custom_cookie_file and os.path.isfile(self.custom_cookie_file):
            return self.custom_cookie_file

        if not self.use_anon_buvid:
            return None

        # 文件存在且未过期，直接复用
        if (
            os.path.isfile(self._anon_cookie_path)
            and (time.time() - self._buvid_fetched_at) < BUVID_CACHE_TTL
        ):
            logger.debug(
                "复用匿名 buvid cookie（距上次更新 %.0f 分钟）",
                (time.time() - self._buvid_fetched_at) / 60,
            )
            return self._anon_cookie_path

        # 过期或缺失，重新拉取
        if self._fetch_and_write_anon_cookies():
            return self._anon_cookie_path
        return None

    def _fetch_and_write_anon_cookies(self) -> bool:
        """从 B 站公开接口获取匿名设备指纹并写入 Netscape 格式文件。"""
        try:
            resp = requests.get(
                FINGER_SPI_URL,
                headers={
                    "User-Agent": self.user_agent,
                    "Referer": "https://www.bilibili.com/",
                    "Origin": "https://www.bilibili.com",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                proxies=self._build_proxies(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.warning("请求 B 站指纹接口失败: %s", e)
            return False
        except ValueError as e:
            logger.warning("指纹接口返回非 JSON 内容: %s", e)
            return False

        if data.get("code") != 0:
            logger.warning("获取 buvid 失败，接口返回码: %s，消息: %s",
                           data.get("code"), data.get("message"))
            return False

        inner = data.get("data") or {}
        b_3 = inner.get("b_3") or ""
        b_4 = inner.get("b_4") or ""
        if not b_3 or not b_4:
            logger.warning("buvid 接口返回数据不完整: %s", inner)
            return False

        # 补充 cookie：buvid_fp 与 b_nut
        buvid_fp = self._gen_buvid_fp()
        b_nut = str(int(time.time()))

        # 写入 Netscape 格式（制表符分隔，末列值，行尾不能有空格）
        lines = [
            "# Netscape HTTP Cookie File",
            "# Generated by bili_downloader (anonymous, no account)",
            "\t".join([".bilibili.com", "TRUE", "/", "FALSE", "0", "buvid3", b_3]),
            "\t".join([".bilibili.com", "TRUE", "/", "FALSE", "0", "buvid4", b_4]),
            "\t".join([".bilibili.com", "TRUE", "/", "FALSE", "0", "buvid_fp", buvid_fp]),
            "\t".join([".bilibili.com", "TRUE", "/", "FALSE", "0", "b_nut", b_nut]),
            "",
        ]

        try:
            with open(self._anon_cookie_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as e:
            logger.warning("写入匿名 cookie 文件失败: %s", e)
            return False

        self._buvid_fetched_at = time.time()
        logger.info(
            "匿名 buvid 指纹获取成功（buvid3=%s...，buvid4=%s...）",
            b_3[:8], b_4[:8],
        )
        return True

    def _build_proxies(self) -> Optional[dict]:
        """为 requests 构造代理配置（获取指纹时也走代理）。"""
        if not self.proxy_url:
            return None
        return {"http": self.proxy_url, "https": self.proxy_url}

    @staticmethod
    def _gen_buvid_fp() -> str:
        """生成一个 32 位 md5 形式的浏览器指纹（B 站只做格式校验，不校验真实来源）。"""
        return hashlib.md5(uuid.uuid4().bytes).hexdigest()