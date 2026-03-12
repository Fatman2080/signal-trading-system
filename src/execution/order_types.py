# -*- coding: utf-8 -*-
"""待执行订单：支持止盈止损、按账号分配或指定固定账号。"""
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class PendingOrder:
    """风控后的待执行订单。"""
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    order_type: str  # "limit" | "market"
    price: Optional[float] = None
    signal_strength: float = 1.0
    account_id: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    extra: dict = field(default_factory=dict)
