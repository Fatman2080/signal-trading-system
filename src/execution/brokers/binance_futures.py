# -*- coding: utf-8 -*-
"""币安 USDT-M 合约交易 Broker。"""
import time
import hmac
import hashlib
from typing import Optional
from urllib.parse import urlencode

from .base import BrokerBase


class BinanceFuturesBroker(BrokerBase):
    """币安 USDT-M 永续合约，支持市价/限价下单。"""

    MAINNET = "https://fapi.binance.com"
    TESTNET = "https://testnet.binancefuture.com"

    def __init__(
        self,
        account_id: str,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        leverage: int = 1,
        recv_window: int = 5000,
        **kwargs,
    ):
        import requests

        self._account_id = account_id
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = self.TESTNET if testnet else self.MAINNET
        self._leverage = leverage
        self._recv_window = recv_window
        self._session = requests.Session()
        self._session.headers.update({"X-MBX-APIKEY": self._api_key})
        self._order_symbols: dict[str, str] = {}
        self._leverage_set: set[str] = set()

    # ── 签名 & 请求 ──────────────────────────────

    def _sign(self, params: dict) -> dict:
        query = urlencode(params)
        sig = hmac.new(
            self._api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = sig
        return params

    def _request(self, method: str, path: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self._recv_window
        params = self._sign(params)
        url = self._base_url + path
        resp = self._session.request(method, url, params=params, timeout=10)
        data = resp.json()
        if resp.status_code != 200:
            code = data.get("code", resp.status_code)
            msg = data.get("msg", resp.text)
            raise RuntimeError(f"Binance API [{code}]: {msg}")
        return data

    def _public_get(self, path: str, params: Optional[dict] = None) -> dict:
        import requests
        url = self._base_url + path
        resp = requests.get(url, params=params or {}, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── 工具 ─────────────────────────────────────

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """统一为币安格式: BTCUSDT"""
        s = symbol.upper().replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
        if not s.endswith("USDT") and not s.endswith("BUSD"):
            s += "USDT"
        return s

    def _ensure_leverage(self, symbol: str) -> None:
        if symbol in self._leverage_set:
            return
        try:
            self._request("POST", "/fapi/v1/leverage", {
                "symbol": symbol,
                "leverage": self._leverage,
            })
            self._leverage_set.add(symbol)
        except Exception as e:
            print(f"[Binance] 设置杠杆失败 {symbol}: {e}")

    # ── 核心接口 ─────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: Optional[float] = None,
    ) -> str:
        bn_symbol = self._normalize_symbol(symbol)
        self._ensure_leverage(bn_symbol)

        params: dict = {
            "symbol": bn_symbol,
            "side": side.upper(),
            "type": order_type.upper(),
        }

        if order_type.upper() == "LIMIT":
            if price is None or price <= 0:
                params["type"] = "MARKET"
            else:
                params["price"] = f"{price}"
                params["timeInForce"] = "GTC"

        params["quantity"] = f"{quantity}"

        result = self._request("POST", "/fapi/v1/order", params)
        order_id = str(result.get("orderId", ""))
        self._order_symbols[order_id] = bn_symbol
        status = result.get("status", "")
        avg_px = result.get("avgPrice", result.get("price", "--"))
        print(
            f"[Binance] {side.upper()} {quantity} {bn_symbol} "
            f"type={params['type']} price={avg_px} status={status} → {order_id}"
        )
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        symbol = self._order_symbols.get(order_id)
        if not symbol:
            print(f"[Binance] cancel: 找不到 orderId={order_id} 对应的交易对")
            return False
        try:
            self._request("DELETE", "/fapi/v1/order", {
                "symbol": symbol,
                "orderId": order_id,
            })
            return True
        except Exception as e:
            print(f"[Binance] cancel error: {e}")
            return False

    def get_account_id(self) -> str:
        return self._account_id

    # ── 查询接口（供风控/仪表盘使用） ────────────

    def get_balance(self) -> dict:
        data = self._request("GET", "/fapi/v2/balance")
        result = {}
        for item in data:
            bal = float(item.get("balance", 0))
            if bal != 0:
                result[item["asset"]] = {
                    "balance": bal,
                    "available": float(item.get("availableBalance", 0)),
                    "unrealized_pnl": float(item.get("crossUnPnl", 0)),
                }
        return result

    def get_positions(self) -> list[dict]:
        data = self._request("GET", "/fapi/v2/positionRisk")
        positions = []
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            positions.append({
                "symbol": p["symbol"],
                "side": "LONG" if amt > 0 else "SHORT",
                "size": abs(amt),
                "entry_price": float(p.get("entryPrice", 0)),
                "unrealized_pnl": float(p.get("unRealizedProfit", 0)),
                "leverage": int(p.get("leverage", 1)),
                "margin_type": p.get("marginType", "cross"),
            })
        return positions

    def get_price(self, symbol: str) -> float:
        bn_symbol = self._normalize_symbol(symbol)
        data = self._public_get("/fapi/v1/ticker/price", {"symbol": bn_symbol})
        return float(data.get("price", 0))
