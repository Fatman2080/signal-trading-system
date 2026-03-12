# -*- coding: utf-8 -*-
"""内联代码信号源：直接在 signals.yaml 配置中编写策略代码，无需创建 Python 文件。

配置示例（signals.yaml）:
  sources:
    - id: my_btc_strategy
      type: inline_code
      weight: 1.0
      symbol: BTC
      interval: 1h
      z_threshold: 1.0
      direction: 1
      code: |
        import pandas as pd
        import numpy as np
        def calculate_factor(df):
            sma_fast = df['close'].rolling(5).mean()
            sma_slow = df['close'].rolling(20).mean()
            return sma_fast - sma_slow
"""
import time
import numpy as np
import pandas as pd
from typing import Optional

from ..base import TradingSignal, SignalDirection
from .registry import register_source
from .alpha_factor import _fetch_binance_klines


def _exec_code(code: str, df: pd.DataFrame, direction: int = 1) -> pd.Series:
    """执行用户内联代码，返回 z-score 信号序列。"""
    scope = {"pd": pd, "np": np}
    exec(code, scope)

    if "calculate_factor" not in scope:
        raise ValueError("代码中必须定义 calculate_factor(df) 函数")

    raw = scope["calculate_factor"](df.copy())

    if not isinstance(raw, pd.Series):
        raw = pd.Series(raw, index=df.index)

    directed = raw * direction
    mean = directed.expanding(min_periods=20).mean()
    std = directed.expanding(min_periods=20).std()
    z_score = (directed - mean) / (std + 1e-6)
    return z_score.fillna(0)


@register_source("inline_code")
class InlineCodeSignalSource:
    """内联代码信号源：在 YAML 配置中直接编写 calculate_factor(df) 函数。

    必需参数:
        code:         Python 代码字符串，必须定义 calculate_factor(df) -> pd.Series

    可选参数:
        symbol:       交易币种（默认 "BTC"）
        interval:     K线周期（默认 "1h"）
        limit:        K线数量（默认 200）
        direction:    信号方向校准，1 或 -1（默认 1）
        z_threshold:  z-score 阈值（默认 1.0）
    """

    def __init__(
        self,
        source_id: str,
        code: str = "",
        account_id: Optional[str] = None,
        symbol: str = "BTC",
        interval: str = "1h",
        limit: int = 200,
        direction: int = 1,
        z_threshold: float = 1.0,
        **kwargs,
    ):
        self.source_id = source_id
        self.code = code
        self.account_id = account_id
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self.direction = direction
        self.z_threshold = z_threshold

        if not code.strip():
            print(f"[InlineCode] 警告: 信号源 {source_id} 未提供 code 代码")
        else:
            lines = code.strip().count("\n") + 1
            print(f"[InlineCode] 已加载信号源: {source_id} ({lines} 行代码, {symbol} {interval})")

    def fetch_signals(self) -> list[TradingSignal]:
        if not self.code.strip():
            return []

        try:
            df = _fetch_binance_klines(self.symbol, self.interval, self.limit)
        except Exception as e:
            print(f"[InlineCode:{self.source_id}] K线获取失败: {e}")
            return []

        try:
            z_scores = _exec_code(self.code, df, self.direction)
        except Exception as e:
            print(f"[InlineCode:{self.source_id}] 代码执行失败: {e}")
            return []

        last_valid_idx = -1
        for i in range(-1, max(-len(z_scores), -6) - 1, -1):
            if z_scores.iloc[i] != 0.0:
                last_valid_idx = i
                break

        latest_z = float(z_scores.iloc[last_valid_idx])
        bar_time = z_scores.index[last_valid_idx] if hasattr(z_scores.index, '__getitem__') else "N/A"
        print(f"[InlineCode:{self.source_id}] {self.symbol} | bar={bar_time} | z={latest_z:+.4f} | 阈值=±{self.z_threshold}")

        if abs(latest_z) < self.z_threshold:
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
            extra={"z_score": round(latest_z, 4), "interval": self.interval},
        )
        dir_str = "做多" if direction == SignalDirection.LONG else "做空"
        print(f"[InlineCode:{self.source_id}] → {dir_str} {self.symbol} 强度={strength:.3f}")
        return [signal]
