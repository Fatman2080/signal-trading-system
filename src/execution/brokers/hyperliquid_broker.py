# -*- coding: utf-8 -*-
"""Hyperliquid 永续合约交易 Broker。"""
import time
import math
from typing import Optional

from .base import BrokerBase


class HyperliquidBroker(BrokerBase):
    """Hyperliquid 永续合约，使用官方 Python SDK。

    配置说明：
        api_secret = 钱包私钥（hex，带或不带 0x 前缀）
        api_key    = 钱包地址（可选，不填则从私钥推导）
        testnet    = true/false
    """

    MAINNET = "https://api.hyperliquid.xyz"
    TESTNET = "https://api.hyperliquid-testnet.xyz"

    def __init__(
        self,
        account_id: str,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = False,
        slippage: float = 0.03,
        **kwargs,
    ):
        from eth_account import Account as EthAccount
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info

        self._account_id = account_id
        self._slippage = slippage
        base_url = self.TESTNET if testnet else self.MAINNET

        private_key = api_secret
        if private_key and not private_key.startswith("0x"):
            private_key = "0x" + private_key

        self._wallet = EthAccount.from_key(private_key)
        self._address = api_key.strip() if api_key.strip() else self._wallet.address

        self._info = Info(base_url, skip_ws=True)
        self._exchange = Exchange(self._wallet, base_url)

        self._sz_decimals: dict[str, int] = {}
        self._order_coins: dict[str, str] = {}
        self._load_meta()

    def _load_meta(self) -> None:
        """缓存币种精度信息。"""
        try:
            meta = self._info.meta()
            for item in meta.get("universe", []):
                self._sz_decimals[item["name"]] = item.get("szDecimals", 3)
        except Exception as e:
            print(f"[Hyperliquid] 加载 meta 失败: {e}")

    # ── 工具 ─────────────────────────────────────

    @staticmethod
    def _normalize_coin(symbol: str) -> str:
        """统一为 Hyperliquid 格式: ETH, BTC（不带 USDT 后缀）"""
        s = symbol.upper().replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
        for suffix in ("USDT", "USD", "PERP", "BUSD"):
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[: -len(suffix)]
        return s

    def _round_size(self, coin: str, sz: float) -> float:
        decimals = self._sz_decimals.get(coin, 3)
        factor = 10 ** decimals
        return math.floor(sz * factor) / factor

    @staticmethod
    def _round_price(px: float, sig: int = 5) -> float:
        if px == 0:
            return 0.0
        d = math.ceil(math.log10(abs(px)))
        return round(px, sig - d)

    # ── 核心接口 ─────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: Optional[float] = None,
    ) -> str:
        coin = self._normalize_coin(symbol)
        is_buy = side.lower() in ("buy", "long")
        sz = self._round_size(coin, quantity)

        if sz <= 0:
            raise ValueError(f"下单数量为 0（{coin} 精度 {self._sz_decimals.get(coin, '?')} 位）")

        if order_type.lower() == "market" or price is None or price <= 0:
            result = self._market_order(coin, is_buy, sz)
        else:
            px = self._round_price(price)
            result = self._exchange.order(
                coin, is_buy, sz, px,
                {"limit": {"tif": "Gtc"}},
            )

        return self._parse_result(result, coin, side, sz)

    def _market_order(self, coin: str, is_buy: bool, sz: float) -> dict:
        """市价单：优先 SDK 原生方法，回退 IOC 限价。"""
        try:
            return self._exchange.market_open(coin, is_buy, sz)
        except (AttributeError, TypeError):
            pass

        mid = float(self._info.all_mids().get(coin, 0))
        if mid <= 0:
            raise ValueError(f"无法获取 {coin} 价格")
        px = mid * (1 + self._slippage) if is_buy else mid * (1 - self._slippage)
        px = self._round_price(px)
        return self._exchange.order(coin, is_buy, sz, px, {"limit": {"tif": "Ioc"}})

    def _parse_result(self, result: dict, coin: str, side: str, sz: float) -> str:
        status = result.get("status", "")
        if status != "ok":
            err = result.get("response", str(result))
            raise RuntimeError(f"Hyperliquid 下单失败: {err}")

        resp = result.get("response", {})
        data = resp.get("data", {})
        statuses = data.get("statuses", [])

        oid = ""
        fill_info = ""
        if statuses:
            s0 = statuses[0]
            if "resting" in s0:
                oid = str(s0["resting"]["oid"])
                fill_info = "挂单中"
            elif "filled" in s0:
                oid = str(s0["filled"]["oid"])
                avg = s0["filled"].get("avgPx", "--")
                total = s0["filled"].get("totalSz", "--")
                fill_info = f"已成交 avg={avg} sz={total}"
            elif "error" in s0:
                raise RuntimeError(f"Hyperliquid 下单错误: {s0['error']}")

        if not oid:
            oid = f"hl_{int(time.time()*1000)}"

        self._order_coins[oid] = coin
        side_cn = "做多" if side.lower() in ("buy", "long") else "做空"
        print(f"[Hyperliquid] {side_cn} {sz} {coin} {fill_info} → oid={oid}")
        return oid

    def place_tp_sl(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> list[str]:
        """开仓成交后挂止盈止损条件单，返回条件单 oid 列表。"""
        coin = self._normalize_coin(symbol)
        is_buy = side.lower() in ("buy", "long")
        sz = self._round_size(coin, quantity)
        if sz <= 0:
            return []

        # TP/SL 平仓方向与开仓相反
        close_is_buy = not is_buy
        oids: list[str] = []

        if stop_loss and stop_loss > 0:
            sl_px = self._round_price(stop_loss)
            try:
                result = self._exchange.order(
                    coin, close_is_buy, sz, sl_px,
                    {"trigger": {"triggerPx": sl_px, "isMarket": True, "tpsl": "sl"}},
                    reduce_only=True,
                )
                oid = self._parse_trigger_result(result, coin, "SL", sl_px)
                if oid:
                    oids.append(oid)
            except Exception as e:
                print(f"[Hyperliquid] 止损单失败 {coin}: {e}")

        if take_profit and take_profit > 0:
            tp_px = self._round_price(take_profit)
            try:
                result = self._exchange.order(
                    coin, close_is_buy, sz, tp_px,
                    {"trigger": {"triggerPx": tp_px, "isMarket": True, "tpsl": "tp"}},
                    reduce_only=True,
                )
                oid = self._parse_trigger_result(result, coin, "TP", tp_px)
                if oid:
                    oids.append(oid)
            except Exception as e:
                print(f"[Hyperliquid] 止盈单失败 {coin}: {e}")

        return oids

    def _parse_trigger_result(self, result: dict, coin: str, label: str, px: float) -> str:
        status = result.get("status", "")
        if status != "ok":
            print(f"[Hyperliquid] {label}单返回异常: {result}")
            return ""
        resp = result.get("response", {})
        data = resp.get("data", {})
        statuses = data.get("statuses", [])
        if statuses:
            s0 = statuses[0]
            if "resting" in s0:
                oid = str(s0["resting"]["oid"])
                print(f"[Hyperliquid] {label}条件单已挂 {coin} @ {px} → oid={oid}")
                return oid
            if "error" in s0:
                print(f"[Hyperliquid] {label}单错误: {s0['error']}")
                return ""
        oid = f"hl_tpsl_{int(time.time()*1000)}"
        print(f"[Hyperliquid] {label}条件单已提交 {coin} @ {px}")
        return oid

    def cancel_order(self, order_id: str) -> bool:
        coin = self._order_coins.get(order_id)
        if not coin:
            print(f"[Hyperliquid] cancel: 找不到 oid={order_id} 对应的币种")
            return False
        if not order_id.isdigit():
            print(f"[Hyperliquid] cancel: oid={order_id} 非数字格式，无法撤单（可能是已成交的市价单）")
            return False
        try:
            self._exchange.cancel(coin, int(order_id))
            return True
        except Exception as e:
            print(f"[Hyperliquid] cancel error: {e}")
            return False

    def get_account_id(self) -> str:
        return self._account_id

    # ── 查询接口 ─────────────────────────────────

    def get_balance(self) -> dict:
        state = self._info.user_state(self._address)
        margin = state.get("marginSummary", {})
        return {
            "account_value": float(margin.get("accountValue", 0)),
            "total_margin_used": float(margin.get("totalMarginUsed", 0)),
            "total_ntl_pos": float(margin.get("totalNtlPos", 0)),
            "available": float(margin.get("accountValue", 0)) - float(margin.get("totalMarginUsed", 0)),
        }

    def get_positions(self) -> list[dict]:
        state = self._info.user_state(self._address)
        positions = []
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            size = float(pos.get("szi", 0))
            if size == 0:
                continue
            lev_info = pos.get("leverage", {})
            lev_val = lev_info.get("value", 1) if isinstance(lev_info, dict) else lev_info
            positions.append({
                "symbol": pos.get("coin", ""),
                "side": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(pos.get("entryPx", 0)),
                "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                "leverage": int(float(lev_val)),
            })
        return positions

    def get_price(self, symbol: str) -> float:
        coin = self._normalize_coin(symbol)
        mids = self._info.all_mids()
        return float(mids.get(coin, 0))
