# -*- coding: utf-8 -*-
"""Webhook 信号源：从全局信号队列中读取外部推送的信号。"""
from typing import Optional

from ..base import TradingSignal
from ..queue import get_signal_queue
from .registry import register_source


@register_source("webhook")
class WebhookSignalSource:
    """从全局信号队列中消费信号，由 POST /api/webhook 写入。"""

    def __init__(
        self,
        source_id: str,
        account_id: Optional[str] = None,
        **kwargs,
    ):
        self.source_id = source_id
        self.account_id = account_id

    def fetch_signals(self) -> list[TradingSignal]:
        queue = get_signal_queue()
        signals = queue.drain()
        if self.account_id:
            for s in signals:
                if s.account_id is None:
                    s.account_id = self.account_id
        return signals
