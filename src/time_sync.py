"""服务器时间校准。

多次请求大麦页面读取 HTTP Date 响应头，选 RTT 最小的样本计算偏移量，
目标：本地判定"现在几点"与服务器误差 < 200ms。
"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

# Date 头精度只有秒，请求开销按 RTT/2 折算后误差通常在几百毫秒内，够用
SAMPLE_COUNT = 5
PROBE_URL = "https://www.damai.cn/"


@dataclass(frozen=True)
class TimeSync:
    """offset = 服务器时间 - 本地时间（秒）"""

    offset: float
    rtt_ms: float

    @classmethod
    def calibrate(cls, probe_url: str = PROBE_URL, samples: int = SAMPLE_COUNT) -> "TimeSync":
        best_offset = 0.0
        best_rtt = float("inf")
        success = 0

        for _ in range(samples):
            try:
                req = urllib.request.Request(
                    probe_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                t0 = time.time()
                with urllib.request.urlopen(req, timeout=3) as resp:
                    date_header = resp.headers.get("Date")
                t1 = time.time()
                if not date_header:
                    continue
                server_ts = parsedate_to_datetime(date_header).timestamp()
                rtt = t1 - t0
                # 服务器时间在响应生成时刻，本地对应时刻约为 t0 + rtt/2
                offset = server_ts - (t0 + rtt / 2)
                success += 1
                if rtt < best_rtt:
                    best_rtt = rtt
                    best_offset = offset
            except OSError:
                continue

        if success == 0:
            raise RuntimeError("时间校准失败：无法获取大麦服务器时间，请检查网络")
        return cls(offset=best_offset, rtt_ms=best_rtt * 1000)

    def now(self) -> float:
        """校准后的当前时间（Unix 时间戳）"""
        return time.time() + self.offset
