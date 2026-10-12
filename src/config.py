"""配置加载与校验。

所有字段缺失或非法都会抛出带中文说明的 ConfigError，绝不让脚本带着错误配置跑起来。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

# 开售时间统一按北京时间解析
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class ConfigError(Exception):
    """配置文件错误（中文提示信息）"""


@dataclass(frozen=True)
class Config:
    show_url: str
    session: str
    ticket: str
    quantity: int
    sale_time: datetime  # 已带北京时区
    refresh_interval_ms: int
    refresh_jitter_ms: int
    max_retry_minutes: int

    @property
    def sale_timestamp(self) -> float:
        """开售时刻的 Unix 时间戳"""
        return self.sale_time.timestamp()


def load_config(path: str | Path) -> Config:
    """读取并校验 YAML 配置文件"""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在：{config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError("配置文件格式错误：应为 YAML 键值对")

    def require(key: str):
        if key not in raw or raw[key] in (None, ""):
            raise ConfigError(f"配置缺少必填项：{key}")
        return raw[key]

    show_url = str(require("show_url"))
    if "damai.cn" not in show_url:
        raise ConfigError(f"show_url 必须是大麦链接，当前值：{show_url}")

    session = str(require("session"))
    ticket = str(require("ticket"))

    quantity = require("quantity")
    if not isinstance(quantity, int) or quantity < 1 or quantity > 6:
        raise ConfigError(f"quantity 必须是 1~6 的整数（大麦单笔限购），当前值：{quantity}")

    sale_time_raw = str(require("sale_time"))
    try:
        sale_time = datetime.strptime(sale_time_raw, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=BEIJING_TZ
        )
    except ValueError:
        raise ConfigError(
            f"sale_time 格式错误，应为 'YYYY-MM-DD HH:MM:SS'，当前值：{sale_time_raw}"
        ) from None

    interval = int(raw.get("refresh_interval_ms", 500))
    if interval < 500:
        # 低于 500ms 风控风险明显上升，强制钳制
        interval = 500
    jitter = int(raw.get("refresh_jitter_ms", 200))
    max_retry = int(raw.get("max_retry_minutes", 10))

    return Config(
        show_url=show_url,
        session=session,
        ticket=ticket,
        quantity=quantity,
        sale_time=sale_time,
        refresh_interval_ms=interval,
        refresh_jitter_ms=jitter,
        max_retry_minutes=max_retry,
    )
