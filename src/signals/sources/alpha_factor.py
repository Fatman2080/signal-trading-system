# -*- coding: utf-8 -*-
"""Alpha-X 因子信号源：加载 factors.json 中的量化因子，基于实时 K 线数据计算信号。"""
import json
import time
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

from ..base import TradingSignal, SignalDirection
from .registry import register_source


def _fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 200) -> pd.DataFrame:
    """从币安公开 API 获取 K 线数据（不需要 API Key）。"""
    s = symbol.upper().replace("/", "").replace("-", "")
    if not s.endswith("USDT"):
        s += "USDT"

    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": s, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame(data, columns=[
        "open_time", "Open", "High", "Low", "Close", "Volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = df[col].astype(float)
    df.index = pd.to_datetime(df["open_time"], unit="ms")

    df["open"] = df["Open"]
    df["high"] = df["High"]
    df["low"] = df["Low"]
    df["close"] = df["Close"]
    df["volume"] = df["Volume"]
    return df


def _load_factor(factors_path: str, factor_name: str) -> Optional[dict]:
    """从 factors.json 加载指定因子。"""
    p = Path(factors_path)
    if not p.exists():
        return None
    with open(p, "r") as f:
        factors = json.load(f)
    for fac in factors:
        if fac["factor_name"] == factor_name:
            return fac
    return None


def _run_factor(factor: dict, df: pd.DataFrame) -> pd.Series:
    """执行因子代码并返回带方向校准的 z-score 信号。"""
    local_scope = {"pd": pd, "np": np}
    exec(factor["code"], local_scope)
    calc_fn = local_scope["calculate_factor"]
    raw = calc_fn(df.copy())

    directed = raw * factor["direction"]
    mean = directed.expanding(min_periods=20).mean()
    std = directed.expanding(min_periods=20).std()
    z_score = (directed - mean) / (std + 1e-6)
    return z_score.fillna(0)


@register_source("alpha_factor")
class AlphaFactorSignalSource:
    """基于 Alpha-X 因子库的实盘信号源。

    配置参数（通过 signals.yaml 传入）：
        symbol:       交易币种，如 "BTC"（默认）
        interval:     K线周期，如 "1h"（默认）
        limit:        K线数量，默认 200
        factor_name:  使用的因子名称，默认 "alpha_1773090486"
        factors_path: factors.json 路径，默认自动查找
        z_threshold:  z-score 超过此值产生信号，默认 1.0
    """

    def __init__(
        self,
        source_id: str,
        account_id: Optional[str] = None,
        symbol: str = "BTC",
        interval: str = "1h",
        limit: int = 200,
        factor_name: str = "alpha_1773090486",
        factors_path: str = "",
        z_threshold: float = 1.0,
        **kwargs,
    ):
        self.source_id = source_id
        self.account_id = account_id
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self.factor_name = factor_name
        self.z_threshold = z_threshold

        if not factors_path:
            base = Path(__file__).resolve().parent.parent.parent.parent
            factors_path = str(base / "Alpha-X_Top20_Factors" / "factors.json")
        self.factors_path = factors_path

        self._factor = _load_factor(self.factors_path, self.factor_name)
        if self._factor:
            print(f"[AlphaFactor] 已加载因子: {self.factor_name} (Sharpe={self._factor['sharpe']:.2f})")
        else:
            print(f"[AlphaFactor] 警告: 未找到因子 {self.factor_name}，路径: {self.factors_path}")

    def fetch_signals(self) -> list[TradingSignal]:
        if not self._factor:
            return []

        try:
            df = _fetch_binance_klines(self.symbol, self.interval, self.limit)
        except Exception as e:
            print(f"[AlphaFactor] K线获取失败 ({self.symbol}): {e}")
            return []

        try:
            z_scores = _run_factor(self._factor, df)
        except Exception as e:
            print(f"[AlphaFactor] 因子计算失败 ({self.factor_name}): {e}")
            return []

        # 最后一根K线通常未收盘或因 shift(-1) 导致 NaN→0，取最近已完成的K线
        last_valid_idx = -1
        for i in range(-1, max(-len(z_scores), -6) - 1, -1):
            if z_scores.iloc[i] != 0.0:
                last_valid_idx = i
                break
        latest_z = float(z_scores.iloc[last_valid_idx])
        bar_time = z_scores.index[last_valid_idx] if hasattr(z_scores.index, '__getitem__') else "N/A"
        print(f"[AlphaFactor] {self.symbol} | 因子={self.factor_name} | bar={bar_time} | z-score={latest_z:.4f} | 阈值=±{self.z_threshold}")

        if abs(latest_z) < self.z_threshold:
            print(f"[AlphaFactor] z-score 未超阈值，不产生信号")
            return []

        direction = SignalDirection.LONG if latest_z > 0 else SignalDirection.SHORT
        strength = min(abs(latest_z) / 3.0, 1.0)

        signal = TradingSignal(
            symbol=self.symbol,
            direction=direction,
            strength=strength,
            source=self.source_id,
            account_id=self.account_id,
            timestamp=time.time(),
            extra={
                "factor_name": self.factor_name,
                "z_score": round(latest_z, 4),
                "interval": self.interval,
            },
        )
        dir_str = "做多" if direction == SignalDirection.LONG else "做空"
        print(f"[AlphaFactor] → 产生信号: {dir_str} {self.symbol}, 强度={strength:.3f}")
        return [signal]
