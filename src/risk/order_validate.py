# -*- coding: utf-8 -*-
"""订单风控校验：持仓感知（防重复 + 反向平仓）、仓位上限、总敞口限制、日交易计数。"""
import time
from typing import Optional

from ..execution.order_types import PendingOrder


# 模块级日交易计数（跨 run_cycle 持久）
_daily_counter = {"date": "", "count": 0}


def _get_daily_count() -> int:
    today = time.strftime("%Y-%m-%d")
    if _daily_counter["date"] != today:
        _daily_counter["date"] = today
        _daily_counter["count"] = 0
    return _daily_counter["count"]


def _inc_daily_count() -> None:
    today = time.strftime("%Y-%m-%d")
    if _daily_counter["date"] != today:
        _daily_counter["date"] = today
        _daily_counter["count"] = 0
    _daily_counter["count"] += 1


class PositionInfo:
    """某账号在某币种上的持仓摘要。"""
    __slots__ = ("symbol", "side", "size", "entry_price", "notional")

    def __init__(self, symbol: str, side: str, size: float, entry_price: float, notional: float = 0.0):
        self.symbol = symbol.upper()
        self.side = side.upper()      # "LONG" / "SHORT"
        self.size = size
        self.entry_price = entry_price
        self.notional = notional or (size * entry_price)


class OrderValidator:
    """风控过滤器（持仓感知版）。

    核心规则：
      1. 同币种同方向已有持仓 → 跳过（不重复开仓）
      2. 同币种反方向已有持仓 → 生成平仓单 + 可选开新仓
      3. 单币种持仓占比不超过 max_position_pct
      4. 总敞口不超过 max_total_exposure_pct × 权益
      5. 单笔金额不超过 max_single_order_pct × 权益
      6. 日交易笔数上限
      7. 标的白名单
    """

    def __init__(
        self,
        allowed_symbols: Optional[list[str]] = None,
        max_single_order_pct: Optional[float] = None,
        max_position_pct: Optional[float] = None,
        max_total_exposure_pct: Optional[float] = None,
        max_daily_trades: Optional[int] = None,
    ):
        self.allowed_symbols = {s.upper() for s in (allowed_symbols or [])}
        self.max_single_order_pct = max_single_order_pct
        self.max_position_pct = max_position_pct or 0.5
        self.max_total_exposure_pct = max_total_exposure_pct or 3.0
        self.max_daily_trades = max_daily_trades

    @staticmethod
    def _order_side_to_pos_side(side: str) -> str:
        return "LONG" if side.lower() in ("buy", "long") else "SHORT"

    @staticmethod
    def _opposite_side(order_side: str) -> str:
        return "sell" if order_side.lower() in ("buy", "long") else "buy"

    def filter_orders(
        self,
        orders: list[PendingOrder],
        total_equity: float = 0.0,
        positions: Optional[list[PositionInfo]] = None,
        prices: Optional[dict[str, float]] = None,
    ) -> tuple[list[PendingOrder], list[PendingOrder]]:
        """过滤订单，返回 (close_orders, open_orders)。

        close_orders: 需要先执行的平仓单
        open_orders:  通过风控的新开仓单
        """
        positions = positions or []
        prices = prices or {}

        pos_map: dict[str, PositionInfo] = {}
        for p in positions:
            pos_map[p.symbol] = p

        current_exposure = sum(p.notional for p in positions)

        close_orders: list[PendingOrder] = []
        open_orders: list[PendingOrder] = []

        for o in orders:
            sym = o.symbol.upper()

            # ── 白名单 ──
            if self.allowed_symbols and sym not in self.allowed_symbols:
                print(f"[风控] 拒绝 {o.symbol}: 不在白名单中")
                continue

            if o.quantity <= 0:
                print(f"[风控] 拒绝 {o.symbol}: 数量 <= 0")
                continue

            # ── 日交易上限 ──
            if self.max_daily_trades and _get_daily_count() >= self.max_daily_trades:
                print(f"[风控] 拒绝 {o.symbol}: 超过日最大交易笔数 {self.max_daily_trades}")
                continue

            order_pos_side = self._order_side_to_pos_side(o.side)
            existing = pos_map.get(sym)

            _side_cn = {"LONG": "多", "SHORT": "空"}

            # ── 规则1: 同方向已有仓位 → 跳过 ──
            if existing and existing.side == order_pos_side:
                print(f"[风控] 跳过 {o.symbol} {o.side}: 已有{_side_cn.get(existing.side, existing.side)}仓 {existing.size}，不重复开仓")
                continue

            # ── 规则2: 反方向已有仓位 → 生成平仓单 ──
            if existing and existing.side != order_pos_side:
                close_side = self._opposite_side(
                    "buy" if existing.side == "LONG" else "sell"
                )
                close_orders.append(PendingOrder(
                    symbol=o.symbol,
                    side=close_side,
                    quantity=existing.size,
                    order_type="market",
                    price=prices.get(sym),
                    signal_strength=o.signal_strength,
                    account_id=o.account_id,
                ))
                print(f"[风控] 反向信号 → 先平{_side_cn.get(existing.side, existing.side)}仓 {existing.size} {o.symbol}")
                current_exposure -= existing.notional
                del pos_map[sym]

            # ── 单笔金额上限 ──
            price = o.price or prices.get(sym, 0)
            if (
                total_equity > 0
                and self.max_single_order_pct is not None
                and price > 0
            ):
                order_value = o.quantity * price
                max_value = total_equity * self.max_single_order_pct
                if order_value > max_value:
                    o.quantity = max_value / price
                    print(f"[风控] {o.symbol}: 订单金额削减至 {o.quantity:.4f} (上限 {max_value:.2f})")

            # ── 单币种仓位上限 ──
            if total_equity > 0 and price > 0:
                existing_notional = pos_map.get(sym, PositionInfo(sym, "", 0, 0)).notional
                new_notional = o.quantity * price
                max_pos_value = total_equity * self.max_position_pct
                if existing_notional + new_notional > max_pos_value:
                    allowed = max(0, max_pos_value - existing_notional)
                    if allowed <= 0:
                        print(f"[风控] 拒绝 {o.symbol}: 仓位已达上限 {max_pos_value:.2f}")
                        continue
                    o.quantity = allowed / price
                    print(f"[风控] {o.symbol}: 仓位削减至 {o.quantity:.4f} (仓位上限 {self.max_position_pct*100:.0f}%)")

            # ── 总敞口上限 ──
            if total_equity > 0 and price > 0:
                new_notional = o.quantity * price
                max_exposure = total_equity * self.max_total_exposure_pct
                if current_exposure + new_notional > max_exposure:
                    allowed = max(0, max_exposure - current_exposure)
                    if allowed <= 0:
                        print(f"[风控] 拒绝 {o.symbol}: 总敞口已达上限 {max_exposure:.2f}")
                        continue
                    o.quantity = allowed / price
                    print(f"[风控] {o.symbol}: 总敞口削减至 {o.quantity:.4f}")

            if o.quantity <= 0:
                continue

            open_orders.append(o)
            _inc_daily_count()

            if price > 0:
                current_exposure += o.quantity * price

        return close_orders, open_orders
