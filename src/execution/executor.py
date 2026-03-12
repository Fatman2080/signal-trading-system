# -*- coding: utf-8 -*-
"""多账号执行器：下单 + 自动挂止盈止损。"""
import traceback

from .account_manager import AccountManager
from .order_types import PendingOrder


_SIDE_CN = {"buy": "做多", "sell": "做空"}


def _side_label(side: str) -> str:
    return _SIDE_CN.get(side.lower(), side)


class MultiAccountExecutor:
    """执行待执行订单，成交后自动挂 TP/SL 条件单。"""

    def __init__(self, account_manager: AccountManager, dry_run: bool = False):
        self.account_manager = account_manager
        self.dry_run = dry_run
        self.errors: list[str] = []
        self.filled_orders: list[dict] = []

    def _place_safe(self, client, account_id: str, order: PendingOrder) -> str:
        try:
            oid = client.place_order(
                symbol=order.symbol, side=order.side, quantity=order.quantity,
                order_type=order.order_type, price=order.price,
            )
            if oid and (order.stop_loss or order.take_profit):
                self._place_tp_sl(client, account_id, order, oid)
            return oid
        except Exception as e:
            err = f"[Executor] 下单失败 [{account_id}] {_side_label(order.side)} {order.quantity} {order.symbol}: {e}"
            print(err)
            traceback.print_exc()
            self.errors.append(err)
            return ""

    def _place_tp_sl(self, client, account_id: str, order: PendingOrder, main_oid: str) -> None:
        if not hasattr(client, "place_tp_sl"):
            return
        try:
            tp_sl_oids = client.place_tp_sl(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )
            if tp_sl_oids:
                print(f"[Executor] 已挂 {len(tp_sl_oids)} 笔 TP/SL 条件单")
        except Exception as e:
            print(f"[Executor] TP/SL 挂单失败 [{account_id}] {order.symbol}: {e}")

    def execute_orders(self, orders: list[PendingOrder]) -> list[str]:
        order_ids: list[str] = []
        self.errors.clear()
        for order in orders:
            if order.account_id is not None:
                client = self.account_manager.get_client(order.account_id)
                if client is None:
                    self.errors.append(f"[Executor] 账号 {order.account_id} 不存在或创建失败")
                    continue
                if self.dry_run:
                    sl_str = f" SL={order.stop_loss}" if order.stop_loss else ""
                    tp_str = f" TP={order.take_profit}" if order.take_profit else ""
                    print(f"[DryRun] {order.account_id}: {_side_label(order.side)} {order.quantity} {order.symbol}{sl_str}{tp_str}")
                    order_ids.append(f"dry_{order.account_id}_{order.symbol}")
                    continue
                oid = self._place_safe(client, order.account_id, order)
                if oid:
                    order_ids.append(oid)
                    self.filled_orders.append({
                        "order_id": oid,
                        "account_id": order.account_id,
                        "symbol": order.symbol,
                        "side": order.side,
                        "quantity": order.quantity,
                        "price": order.price,
                        "stop_loss": order.stop_loss,
                        "take_profit": order.take_profit,
                        "extra": order.extra,
                    })
            else:
                weights = self.account_manager.get_weights()
                for account_id, w in weights:
                    if w <= 0:
                        continue
                    qty = order.quantity * w
                    if qty <= 0:
                        continue
                    client = self.account_manager.get_client(account_id)
                    if client is None:
                        continue
                    sub_order = PendingOrder(
                        symbol=order.symbol, side=order.side, quantity=qty,
                        order_type=order.order_type, price=order.price,
                        signal_strength=order.signal_strength, account_id=account_id,
                        stop_loss=order.stop_loss, take_profit=order.take_profit,
                        extra=order.extra,
                    )
                    if self.dry_run:
                        print(f"[DryRun] {account_id}: {_side_label(order.side)} {qty} {order.symbol}")
                        order_ids.append(f"dry_{account_id}_{order.symbol}")
                        continue
                    oid = self._place_safe(client, account_id, sub_order)
                    if oid:
                        order_ids.append(oid)
                        self.filled_orders.append({
                            "order_id": oid,
                            "account_id": account_id,
                            "symbol": order.symbol,
                            "side": order.side,
                            "quantity": qty,
                            "price": order.price,
                            "stop_loss": order.stop_loss,
                            "take_profit": order.take_profit,
                            "extra": order.extra,
                        })
        if self.errors:
            print(f"[Executor] 本轮共 {len(self.errors)} 笔下单失败")
        return order_ids
