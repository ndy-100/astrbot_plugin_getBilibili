"""下载核心模块：基于 bilibili-api 获取 playurl，自行下载 DASH 流并用 ffmpeg 合并。

这个版本解决了单节点 CDN 返回 567 错误的问题：
拿到主直链的同时提取备份直链，一旦主链接失败，自动无缝切换重试。
"""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import aiohttp
import requests

from bilibili_api import video, Credential

from .models import ParsedVideo, MediaStream, PreparedFile

logger = logging.getLogger("bili_downloader.downloader")

# B 站 API 和 CDN 硬性要求的 Referer / Origin
BILI_REFERER = "https://www.bilibili.com/"
BILI_ORIGIN = "https://www.bilibili.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class BiliDownloader:
    def __init__(self, config: dict, cookie_dir: str):
        self.config = config
        self.cookie_dir = cookie_dir
        self.max_filesize_mb = int(config.get("max_filesize_mb", 100))
        self.max_height = int(config.get("max_height", 720))
        self.user_agent = config.get("user_agent", DEFAULT_UA)
        self.proxy_url = (config.get("proxy_url") or "").strip()

        self._semaphore = asyncio.Semaphore(int(config.get("max_concurrent", 2)))

    # ===================== 对外接口 =====================

    async def download(self, url: str, temp_root: str) -> Tuple[str, float]:
        """下载视频并返回 (最终文件路径, 大小MB)。失败时抛出异常。"""
        async with self._semaphore:
            return await self._do_download(url, temp_root)

    # ===================== 内部流程 =====================

    async def _do_download(self, url: str, temp_root: str) -> Tuple[str, float]:
        task_dir = Path(tempfile.mkdtemp(dir=temp_root, prefix="bili_"))
        try:
            # 1. 解析
            parsed = await self._parse(url)
            logger.info(
                "解析成功: %s | 标题=%s | durl=%s | DASH 流数=%d",
                parsed.bvid,
                parsed.title,
                "是" if parsed.direct_url else "否",
                len(parsed.dash_streams),
            )

            # 2. 下载并合并
            prepared = await self._prepare(parsed, task_dir)

            # 3. 校验文件大小
            size_mb = prepared.size_bytes / (1024 * 1024)
            if size_mb > self.max_filesize_mb * 1.1:
                raise RuntimeError(
                    f"文件大小 {size_mb:.1f}MB 超过限制 {self.max_filesize_mb}MB"
                )

            return str(prepared.path), size_mb
        except Exception:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise

    # ===================== 解析 =====================

    async def _parse(self, url: str) -> ParsedVideo:
        """用 bilibili-api 获取视频信息和 playurl，直接解析原始数据。"""
        bvid = self._extract_bvid(url)
        if not bvid:
            raise ValueError(f"无法从链接中提取 BV 号: {url}")

        credential = Credential()
        v = video.Video(bvid=bvid, credential=credential)
        info = await v.get_info()

        play_data = await v.get_download_url(0)
        if not isinstance(play_data, dict):
            raise RuntimeError(f"get_download_url 返回类型异常: {type(play_data)}")

        title = info.get("title", "") or ""
        duration = info.get("duration", 0) or 0

        # ---------- 情况 A：durl 模式（旧视频 / 少数特定格式） ----------
        durl = play_data.get("durl")
        if isinstance(durl, list) and durl:
            first = durl[0] or {}
            direct_url = first.get("url") or ""
            if direct_url:
                logger.info("使用 durl 合并流模式")
                return ParsedVideo(
                    bvid=bvid,
                    title=title,
                    duration=duration,
                    direct_url=direct_url,
                )

        # ---------- 情况 B：DASH 模式（主流） ----------
        dash = play_data.get("dash") or {}
        video_streams = dash.get("video") or []
        audio_streams = dash.get("audio") or []

        if not video_streams:
            raise RuntimeError("该视频没有可用的 DASH 视频流")

        streams: list[MediaStream] = []

        # ---- 选视频流：优先不超 max_height，同等条件下取带宽最高 ----
        video_candidates = [
            s for s in video_streams
            if isinstance(s, dict) and (s.get("height", 0) or 0) <= self.max_height
        ]
        if not video_candidates:
            # 全部超限 → 取最低码率的
            video_candidates = sorted(
                [s for s in video_streams if isinstance(s, dict)],
                key=lambda s: (s.get("height", 0) or 0, s.get("bandwidth", 0) or 0),
            )[:1]
            logger.warning("所有视频流均超过 max_height=%d，退而选择最低码率", self.max_height)

        if video_candidates:
            chosen_v = max(
                video_candidates,
                key=lambda s: (s.get("height", 0) or 0, s.get("bandwidth", 0) or 0),
            )
            url_v = self._pick_url(chosen_v)
            backups_v = self._pick_backups(chosen_v)
            if url_v:
                streams.append(MediaStream(
                    url=url_v,
                    type="video",
                    backup_urls=backups_v,
                    codec=chosen_v.get("codecs", "") or "",
                    width=chosen_v.get("width", 0) or 0,
                    height=chosen_v.get("height", 0) or 0,
                    bandwidth=chosen_v.get("bandwidth", 0) or 0,
                ))

        # ---- 选音频流：带宽最高 ----
        if audio_streams:
            audio_candidates = [s for s in audio_streams if isinstance(s, dict)]
            if audio_candidates:
                best_a = max(audio_candidates, key=lambda s: s.get("bandwidth", 0) or 0)
                url_a = self._pick_url(best_a)
                backups_a = self._pick_backups(best_a)
                if url_a:
                    streams.append(MediaStream(
                        url=url_a,
                        type="audio",
                        backup_urls=backups_a,
                        codec=best_a.get("codecs", "") or "",
                        bandwidth=best_a.get("bandwidth", 0) or 0,
                    ))

        if not streams:
            raise RuntimeError("没有找到可用的媒体流")

        return ParsedVideo(
            bvid=bvid,
            title=title,
            duration=duration,
            dash_streams=streams,
        )

    @staticmethod
    def _pick_url(stream: dict) -> str:
        """从流字典中取主 URL。"""
        return stream.get("baseUrl") or stream.get("base_url") or ""

    @staticmethod
    def _pick_backups(stream: dict) -> list[str]:
        """从流字典中取备用 URL 列表。"""
        return stream.get("backupUrl") or stream.get("backup_url") or []

    def _extract_bvid(self, url: str) -> Optional[str]:
        """从 B 站长链 / 短链中提取 BV 号。短链需同步请求一次重定向。"""
        m = re.search(r"/video/(BV[A-Za-z0-9]+)", url)
        if m:
            return m.group(1)

        if "b23.tv" in url:
            try:
                r = requests.get(
                    url,
                    headers={"User-Agent": self.user_agent, "Referer": BILI_REFERER},
                    allow_redirects=True,
                    timeout=10,
                )
                m = re.search(r"/video/(BV[A-Za-z0-9]+)", r.url)
                if m:
                    return m.group(1)
            except Exception as e:
                logger.warning("短链解析失败: %s", e)
        return None

    # ===================== 下载 + 合并 =====================

    async def _prepare(self, parsed: ParsedVideo, task_dir: Path) -> PreparedFile:
        """下载所有轨道到本地，必要时用 ffmpeg 合并为 mp4。"""
        headers = {
            "User-Agent": self.user_agent,
            "Referer": BILI_REFERER,
            "Origin": BILI_ORIGIN,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        async with aiohttp.ClientSession(
            headers=headers,
            trust_env=bool(self.proxy_url),
        ) as session:
            # ---------- durl 模式：单文件，ffmpeg 转封装 ----------
            if parsed.direct_url:
                raw = task_dir / "direct_raw.bin"
                await self._download_stream(session, parsed.direct_url, [], raw)
                final = task_dir / "output.mp4"
                await self._remux_with_ffmpeg(raw, final)
                size = final.stat().st_size
                return PreparedFile(path=final, size_bytes=size, cleanup_paths=[raw])

            # ---------- DASH 模式 ----------
            if not parsed.dash_streams:
                raise RuntimeError("没有可用的媒体流")

            downloaded: list[Path] = []
            for i, stream in enumerate(parsed.dash_streams):
                out = task_dir / f"stream_{i}.m4s"
                # 传入备用 URL 列表，交给 _download_stream 内部去重试
                await self._download_stream(session, stream.url, stream.backup_urls, out)
                downloaded.append(out)

        if len(downloaded) == 1:
            final = task_dir / "output.mp4"
            os.replace(downloaded[0], final)
            cleanup: list[Path] = []
        else:
            final = task_dir / "output.mp4"
            await self._merge_with_ffmpeg(downloaded, final)
            cleanup = [p for p in downloaded if p != final]

        size = final.stat().st_size
        return PreparedFile(path=final, size_bytes=size, cleanup_paths=cleanup)

    async def _download_stream(
        self, session: aiohttp.ClientSession, url: str, backups: list[str], out: Path
    ) -> None:
        """流式下载单个轨道。如果主链接失败（如 567），自动尝试备用链接。"""
        urls_to_try = [url] + backups
        last_error = None

        for attempt_url in urls_to_try:
            logger.info("开始下载: %s", attempt_url[:100])
            try:
                async with session.get(attempt_url) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:100]
                        raise RuntimeError(f"HTTP {resp.status} | {body}")
                    
                    with open(out, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 1024):
                            f.write(chunk)
                
                logger.info("下载成功: %s (%d bytes)", out.name, out.stat().st_size)
                return  # 成功就退出整个函数
            except Exception as e:
                logger.warning("节点被拒或失效 (%s)，尝试下一个备用节点...", str(e))
                last_error = e
        
        # 所有地址都试过了
        raise RuntimeError(f"所有下载地址均失败，最后一个错误: {last_error}")

    @staticmethod
    async def _merge_with_ffmpeg(inputs: list[Path], out: Path) -> None:
        """调用 ffmpeg 无重编码合并音视频轨（-c copy）。"""
        cmd = ["ffmpeg", "-y"]
        for p in inputs:
            cmd += ["-i", str(p)]
        cmd += ["-c", "copy", str(out)]

        logger.info("执行 ffmpeg 合并: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="ignore")[:800]
            raise RuntimeError(f"ffmpeg 合并失败: {err}")

    @staticmethod
    async def _remux_with_ffmpeg(input_file: Path, out: Path) -> None:
        """将单个容器（如 flv）转封装为 mp4，不重编码。"""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_file),
            "-c", "copy",
            str(out),
        ]

        logger.info("执行 ffmpeg 转封装: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="ignore")[:800]
            raise RuntimeError(f"ffmpeg 转封装失败: {err}")