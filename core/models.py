"""数据模型：解析结果与下载产物。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MediaStream:
    """单个媒体轨道（视频轨或音频轨）。"""
    url: str
    type: str          # "video" | "audio"
    backup_urls: list[str] = field(default_factory=list)  # 新增：备用直链列
    codec: str = ""
    width: int = 0
    height: int = 0
    bandwidth: int = 0


@dataclass
class ParsedVideo:
    """解析后得到的视频信息（对应原来 yt-dlp 的 info dict）。"""
    bvid: str
    title: str
    duration: int = 0
    # 合并流的直链（durl 模式，或已经合并好的 mp4）
    direct_url: str = ""
    # 分离流（DASH 模式）：[视频轨, 音频轨]，需要下载后合并
    dash_streams: list[MediaStream] = field(default_factory=list)
    # 备用：低画质但一定可用的合并直链
    fallback_url: str = ""


@dataclass
class PreparedFile:
    """下载/合并完成后的本地文件。"""
    path: Path
    size_bytes: int = 0
    cleanup_paths: list[Path] = field(default_factory=list)