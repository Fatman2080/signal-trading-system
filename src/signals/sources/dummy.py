# -*- coding: utf-8 -*-
"""示例信号源：用于测试与演示。"""
from typing import Optional

from ..base import TradingSignal, SignalDirection
from .registry import register_source


@register_source("dummy")
class DummySignalSource:
    """返回可配置的模拟信号，支持指定 account_id。"""

    def __init__(
        self,
        source_id: str,
        account_id: Optional[str] = None,
    ):
        self.source_id = source_id
        self.account_id = account_id

    def fetch_signals(self) -> list[TradingSignal]:
        # 示例：返回空或简单测试信号
        return [
            TradingSignal(
                symbol="600519.SH",
                direction=SignalDirection.LONG,
                strength=0.7,
                source=self.source_id,
                account_id=self.account_id,
            )
        ]
