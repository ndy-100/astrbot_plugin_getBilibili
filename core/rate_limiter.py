"""频率限制模块：每用户冷却 + 每日上限。"""

import datetime
import time
from typing import Dict, Tuple


class RateLimiter:
    def __init__(self, cooldown: int = 30, daily_limit: int = 10):
        self.cooldown = max(0, int(cooldown))
        self.daily_limit = max(0, int(daily_limit))

        self._last_time: Dict[str, float] = {}
        self._daily_count: Dict[str, int] = {}
        self._daily_date: Dict[str, str] = {}

    def check(self, user_id: str) -> Tuple[bool, str]:
        """返回 (是否允许, 拒绝原因)。允许时会自动计数。"""
        now = time.monotonic()
        today = datetime.date.today().isoformat()

        # 跨天重置
        if self._daily_date.get(user_id) != today:
            self._daily_date[user_id] = today
            self._daily_count[user_id] = 0

        # 每日上限
        if self.daily_limit > 0 and self._daily_count.get(user_id, 0) >= self.daily_limit:
            return False, f"⏳ 今日下载次数已达上限（{self.daily_limit} 次/天），请明天再试。"

        # 冷却
        if self.cooldown > 0:
            last = self._last_time.get(user_id, 0.0)
            elapsed = now - last
            if elapsed < self.cooldown:
                wait = int(self.cooldown - elapsed) + 1
                return False, f"⏳ 操作太频繁，请等待 {wait} 秒后再试。"

        # 通过，更新状态
        self._last_time[user_id] = now
        self._daily_count[user_id] = self._daily_count.get(user_id, 0) + 1
        return True, ""