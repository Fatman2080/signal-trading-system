# -*- coding: utf-8 -*-
"""统一信号格式：支持多信号聚合与「信号指定固定账号」执行。"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class SignalDirection(Enum):
    LONG = 1
    SHORT = -1
    NEUTRAL = 0


@dataclass
class TradingSignal:
    """统一信号格式。"""
    symbol: str
    direction: SignalDirection
    strength: float  # 0~1，用于加权
    source: str
    target_weight: Optional[float] = None
    timestamp: float = 0.0
    extra: Optional[dict[str, Any]] = None
    # 指定执行账号：None=按权重分配多账号；非空=仅在该账号执行
    account_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}
