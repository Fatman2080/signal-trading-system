# -*- coding: utf-8 -*-
"""策略引擎：聚合信号 -> 订单，传递 account_id 和 SL/TP。"""
from ..signals.base import TradingSignal, SignalDirection
from ..execution.order_types import PendingOrder


class StrategyEngine:
    """将信号转为待执行订单，保留 account_id 和止盈止损价格。"""

    def __init__(self, order_type: str = "limit", default_price: float = 0.0):
        self.order_type = order_type
        self.default_price = default_price

    def signals_to_orders(
        self,
        signals: list[TradingSignal],
        quantity_per_signal: float = 100.0,
    ) -> list[PendingOrder]:
        orders: list[PendingOrder] = []
        for s in signals:
            if s.direction == SignalDirection.NEUTRAL:
                continue
            side = "buy" if s.direction == SignalDirection.LONG else "sell"
            qty = quantity_per_signal * s.strength
            if qty <= 0:
                continue

            extra = s.extra or {}
            sl = extra.get("stop_loss")
            tp = extra.get("take_profit_1")

            orders.append(
                PendingOrder(
                    symbol=s.symbol,
                    side=side,
                    quantity=qty,
                    order_type=self.order_type,
                    price=self.default_price if self.order_type == "limit" else None,
                    signal_strength=s.strength,
                    account_id=s.account_id,
                    stop_loss=sl,
                    take_profit=tp,
                    extra={
                        "signal_source": s.source,
                        "reasons": extra.get("reasons", []),
                        "take_profit_2": extra.get("take_profit_2"),
                        "ema20": extra.get("ema20"),
                        "atr": extra.get("atr"),
                        "entry_price": extra.get("entry_price"),
                    },
                )
            )
        return orders
