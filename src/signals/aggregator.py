# -*- coding: utf-8 -*-
"""多信号聚合：加权聚合，并继承/传递 account_id。"""
from typing import Optional

from .base import TradingSignal, SignalDirection


class SignalAggregator:
    """多信号聚合。同一标的多个信号按来源权重聚合；若任一来信号带 account_id 则继承。"""

    def __init__(self, source_weights: dict[str, float], min_strength: float = 0.3):
        self.source_weights = source_weights
        self.min_strength = min_strength

    def aggregate(self, signals: list[TradingSignal]) -> list[TradingSignal]:
        if not signals:
            return []
        by_symbol: dict[str, list[TradingSignal]] = {}
        for s in signals:
            by_symbol.setdefault(s.symbol, []).append(s)

        results: list[TradingSignal] = []
        for symbol, sym_signals in by_symbol.items():
            w_sum = sum(self.source_weights.get(s.source, 0.5) for s in sym_signals)
            if w_sum <= 0:
                continue
            direction_val = sum(
                s.direction.value * s.strength * self.source_weights.get(s.source, 0.5)
                for s in sym_signals
            ) / w_sum
            strength = sum(
                s.strength * self.source_weights.get(s.source, 0.5) for s in sym_signals
            ) / w_sum
            if strength < self.min_strength:
                continue

            # 若任一来信号指定了 account_id，聚合结果继承（固定账号执行）
            account_id: Optional[str] = None
            for s in sym_signals:
                if s.account_id is not None:
                    account_id = s.account_id
                    break

            direction = (
                SignalDirection.LONG
                if direction_val > 0
                else (SignalDirection.SHORT if direction_val < 0 else SignalDirection.NEUTRAL)
            )
            results.append(
                TradingSignal(
                    symbol=symbol,
                    direction=direction,
                    strength=min(1.0, strength),
                    source="aggregated",
                    account_id=account_id,
                )
            )
        return results
