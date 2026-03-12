# -*- coding: utf-8 -*-
"""PA + MACD 信号源：Price Action 形态 + MACD 金叉死叉 + 背离 + EMA 趋势过滤 + 成交量确认。

移植自 PA/ 目录的独立策略，整合为可插拔信号源。

配置示例（signals.yaml）:
  sources:
    - id: pa_btc
      type: pa_macd
      weight: 1.0
      symbol: BTC
      interval: 4h
      limit: 250
"""
import time
import numpy as np
import pandas as pd
from typing import Optional

from ..base import TradingSignal, SignalDirection
from .registry import register_source
from .alpha_factor import _fetch_binance_klines

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    from ta.trend import MACD, EMAIndicator
    from ta.volatility import AverageTrueRange

    df = df.dropna()

    macd = MACD(close=df["close"], window_slow=MACD_SLOW, window_fast=MACD_FAST, window_sign=MACD_SIGNAL)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    df["ema200"] = EMAIndicator(close=df["close"], window=200).ema_indicator()
    df["ema20"] = EMAIndicator(close=df["close"], window=20).ema_indicator()
    df["vol_sma20"] = df["volume"].rolling(window=20).mean()
    df["atr"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()

    df = df.dropna()
    return df


def _find_swing_points(df: pd.DataFrame):
    recent = df.iloc[-20:]
    return recent["low"].min(), recent["high"].max()


def _check_candlestick_patterns(df: pd.DataFrame) -> list[str]:
    if len(df) < 3:
        return []
    patterns = []
    curr_o, curr_c = df["open"].iloc[-1], df["close"].iloc[-1]
    curr_h, curr_l = df["high"].iloc[-1], df["low"].iloc[-1]
    prev_o, prev_c = df["open"].iloc[-2], df["close"].iloc[-2]

    if (prev_c < prev_o) and (curr_c > curr_o) and (curr_o <= prev_c) and (curr_c >= prev_o):
        patterns.append("看涨吞没")
    if (prev_c > prev_o) and (curr_c < curr_o) and (curr_o >= prev_c) and (curr_c <= prev_o):
        patterns.append("看跌吞没")

    body = abs(curr_c - curr_o)
    lower_shadow = min(curr_o, curr_c) - curr_l
    upper_shadow = curr_h - max(curr_o, curr_c)
    if body > 0 and lower_shadow >= 2 * body and upper_shadow <= 0.5 * body:
        patterns.append("锤子线")

    return patterns


def _check_divergence(df: pd.DataFrame, window: int = 5) -> list[str]:
    if len(df) < window + 2:
        return []
    signals = []
    cur_price = df["close"].iloc[-1]
    prev_price_low = df["close"].iloc[-window - 1:-1].min()
    cur_hist = df["macd_hist"].iloc[-1]
    prev_hist_low = df["macd_hist"].iloc[-window - 1:-1].min()

    if cur_price < prev_price_low and cur_hist > prev_hist_low and cur_hist < 0:
        signals.append("底背离")

    prev_price_high = df["close"].iloc[-window - 1:-1].max()
    prev_hist_high = df["macd_hist"].iloc[-window - 1:-1].max()
    if cur_price > prev_price_high and cur_hist < prev_hist_high and cur_hist > 0:
        signals.append("顶背离")

    return signals


def _check_crossover(df: pd.DataFrame) -> list[str]:
    if len(df) < 2:
        return []
    signals = []
    curr_macd, curr_sig = df["macd"].iloc[-1], df["macd_signal"].iloc[-1]
    prev_macd, prev_sig = df["macd"].iloc[-2], df["macd_signal"].iloc[-2]

    if prev_macd < prev_sig and curr_macd > curr_sig:
        signals.append("MACD金叉")
    if prev_macd > prev_sig and curr_macd < curr_sig:
        signals.append("MACD死叉")
    return signals


def _analyze(df: pd.DataFrame) -> dict:
    """分析 PA+MACD 信号，返回完整分析结果。

    返回 dict:
        direction: "LONG" / "SHORT" / "NEUTRAL"
        strength:  0~1 归一化强度
        reasons:   触发原因列表
        stop_loss: 止损价
        take_profit_1: 止盈1 (1R)
        take_profit_2: 止盈2 (2R)
        ema20: EMA20 参考离场价
    """
    empty = {"direction": "NEUTRAL", "strength": 0.0, "reasons": []}

    df = _calculate_indicators(df)
    if df.empty:
        return empty

    cur_price = df["close"].iloc[-1]
    ema200 = df["ema200"].iloc[-1]
    ema20 = df["ema20"].iloc[-1]
    cur_vol = df["volume"].iloc[-1]
    vol_sma = df["vol_sma20"].iloc[-1]
    atr = df["atr"].iloc[-1]
    swing_low, swing_high = _find_swing_points(df)

    raw_signals = _check_crossover(df) + _check_divergence(df)
    if not raw_signals:
        return empty

    scored = []
    for sig_text in raw_signals:
        if "金叉" in sig_text or "底背离" in sig_text:
            sig_type = "LONG"
        elif "死叉" in sig_text or "顶背离" in sig_text:
            sig_type = "SHORT"
        else:
            continue

        score = 1.0
        reasons = [sig_text]

        if sig_type == "LONG" and cur_price > ema200:
            score += 1.0
            reasons.append("顺势>EMA200")
        elif sig_type == "SHORT" and cur_price < ema200:
            score += 1.0
            reasons.append("顺势<EMA200")

        if cur_vol > vol_sma:
            score += 0.5
            reasons.append("放量")

        patterns = _check_candlestick_patterns(df)
        for p in patterns:
            if sig_type == "LONG" and ("看涨" in p or "锤子" in p):
                score += 1.5
                reasons.append(p)
            elif sig_type == "SHORT" and ("看跌" in p):
                score += 1.5
                reasons.append(p)

        scored.append((sig_type, score, reasons))

    if not scored:
        return empty

    scored.sort(key=lambda x: x[1], reverse=True)

    has_long = any(s[0] == "LONG" for s in scored)
    has_short = any(s[0] == "SHORT" for s in scored)

    if has_long and has_short:
        long_score = sum(s[1] for s in scored if s[0] == "LONG")
        short_score = sum(s[1] for s in scored if s[0] == "SHORT")
        winner = "LONG" if long_score >= short_score else "SHORT"
        scored = [s for s in scored if s[0] == winner]

    best_type, best_score, best_reasons = scored[0]
    strength = min(best_score / 4.0, 1.0)

    # SL/TP 计算（复用 PA 原始策略的 Swing ± ATR 规则）
    if best_type == "LONG":
        sl = swing_low - atr
        risk = max(cur_price - sl, atr * 0.5)
        tp1 = cur_price + risk
        tp2 = cur_price + 2 * risk
    else:
        sl = swing_high + atr
        risk = max(sl - cur_price, atr * 0.5)
        tp1 = cur_price - risk
        tp2 = cur_price - 2 * risk

    return {
        "direction": best_type,
        "strength": strength,
        "reasons": best_reasons,
        "stop_loss": round(sl, 4),
        "take_profit_1": round(tp1, 4),
        "take_profit_2": round(tp2, 4),
        "ema20": round(ema20, 4),
        "atr": round(atr, 4),
        "entry_price": round(cur_price, 4),
    }


@register_source("pa_macd")
class PAMacdSignalSource:
    """PA + MACD 组合信号源。

    综合 MACD 金叉/死叉、背离、K线形态（吞没/锤子）、
    EMA200 趋势过滤、成交量确认，输出加权评分信号。

    配置参数：
        symbol:    交易币种（默认 BTC）
        interval:  K线周期（默认 4h）
        limit:     K线数量（默认 250，需 >=200 以计算 EMA200）
    """

    def __init__(
        self,
        source_id: str,
        account_id: Optional[str] = None,
        symbol: str = "BTC",
        interval: str = "4h",
        limit: int = 250,
        **kwargs,
    ):
        self.source_id = source_id
        self.account_id = account_id
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        print(f"[PA+MACD] 已加载信号源: {source_id} ({symbol} {interval})")

    def fetch_signals(self) -> list[TradingSignal]:
        try:
            df = _fetch_binance_klines(self.symbol, self.interval, self.limit)
        except Exception as e:
            print(f"[PA+MACD:{self.source_id}] K线获取失败: {e}")
            return []

        try:
            result = _analyze(df)
        except Exception as e:
            print(f"[PA+MACD:{self.source_id}] 分析失败: {e}")
            return []

        direction = result["direction"]
        strength = result["strength"]
        reasons = result["reasons"]

        reasons_str = ", ".join(reasons)
        dir_cn = {"LONG": "做多", "SHORT": "做空", "NEUTRAL": "无"}.get(direction, direction)
        print(f"[PA+MACD:{self.source_id}] {self.symbol} {self.interval} | 方向={dir_cn} | 强度={strength:.2f} | {reasons_str or '无信号'}")

        if direction == "NEUTRAL" or strength <= 0:
            return []

        sl = result["stop_loss"]
        tp1 = result["take_profit_1"]
        tp2 = result["take_profit_2"]
        print(f"[PA+MACD:{self.source_id}] SL={sl} | TP1={tp1} | TP2={tp2}")

        sig_dir = SignalDirection.LONG if direction == "LONG" else SignalDirection.SHORT
        return [
            TradingSignal(
                symbol=self.symbol,
                direction=sig_dir,
                strength=strength,
                source=self.source_id,
                account_id=self.account_id,
                timestamp=time.time(),
                extra={
                    "reasons": reasons,
                    "interval": self.interval,
                    "stop_loss": sl,
                    "take_profit_1": tp1,
                    "take_profit_2": tp2,
                    "ema20": result["ema20"],
                    "atr": result["atr"],
                    "entry_price": result["entry_price"],
                },
            )
        ]
