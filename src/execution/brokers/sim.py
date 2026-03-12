# -*- coding: utf-8 -*-
"""模拟经纪商：仅打印不真实下单，内存追踪虚拟持仓。"""
from typing import Optional

from .base import BrokerBase


class SimBroker(BrokerBase):
    """模拟盘：打印订单信息，内存记录虚拟持仓和余额。"""

    _shared_positions: dict[str, dict[str, dict]] = {}
    _shared_balance: dict[str, float] = {}

    def __init__(self, account_id: str, api_key: str = "", api_secret: str = "", **kwargs):
        self._account_id = account_id
        self._api_key = api_key
        self._api_secret = api_secret
        if account_id not in SimBroker._shared_balance:
            SimBroker._shared_balance[account_id] = 100000.0
        if account_id not in SimBroker._shared_positions:
            SimBroker._shared_positions[account_id] = {}

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: Optional[float] = None,
    ) -> str:
        order_id = f"sim_{self._account_id}_{id(self)}_{hash((symbol, side))}"
        key_hint = self._api_key[:6] + "***" if self._api_key else "无"
        print(
            f"[SimBroker {self._account_id}] key={key_hint} | "
            f"{side} {quantity} {symbol} type={order_type} price={price} → {order_id}"
        )

        positions = SimBroker._shared_positions[self._account_id]
        pos = positions.get(symbol, {"size": 0.0, "side": "LONG", "entry_price": 0.0})
        if side.lower() in ("buy", "long"):
            pos["size"] += quantity
            pos["side"] = "LONG"
            pos["entry_price"] = price or 0.0
        else:
            pos["size"] -= quantity
            if pos["size"] < 0:
                pos["side"] = "SHORT"
                pos["size"] = abs(pos["size"])
            pos["entry_price"] = price or 0.0

        if pos["size"] == 0:
            positions.pop(symbol, None)
        else:
            positions[symbol] = pos

        return order_id

    def cancel_order(self, order_id: str) -> bool:
        print(f"[SimBroker {self._account_id}] cancel_order: {order_id}")
        return True

    def get_account_id(self) -> str:
        return self._account_id

    def get_price(self, symbol: str) -> float:
        """模拟价格：主流币种返回近似价格，其他返回 100。"""
        prices = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0, "BNB": 600.0}
        s = symbol.upper().replace("USDT", "").replace("USD", "").replace("/", "")
        return prices.get(s, 100.0)

    def get_balance(self) -> dict:
        bal = SimBroker._shared_balance.get(self._account_id, 100000.0)
        return {
            "USDT": {
                "balance": bal,
                "available": bal,
            }
        }

    def get_positions(self) -> list[dict]:
        positions = SimBroker._shared_positions.get(self._account_id, {})
        result = []
        for symbol, pos in positions.items():
            result.append({
                "symbol": symbol,
                "side": pos["side"],
                "size": pos["size"],
                "entry_price": pos["entry_price"],
                "unrealized_pnl": 0.0,
                "leverage": 1,
            })
        return result
