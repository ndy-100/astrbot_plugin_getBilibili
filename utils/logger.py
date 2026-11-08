"""日志辅助（可选用）。"""

import logging

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"bili_downloader.{name}")