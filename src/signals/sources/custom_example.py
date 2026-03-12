# -*- coding: utf-8 -*-
"""
自定义信号源模板 —— 把你自己的策略信号代码接入系统。

使用方法：
  1. 复制本文件，重命名为你的信号源名字，例如 my_macd.py
  2. 修改 @register_source("xxx") 中的名字
  3. 在 fetch_signals() 里写你的信号逻辑
  4. 在 config/signals.yaml 中配置 type: "xxx"

系统会自动发现并加载你的信号源，无需修改其他代码。
"""
from typing import Optional
import time

from ..base import TradingSignal, SignalDirection
from .registry import register_source


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 把 "custom_example" 改成你的策略名称
# 这个名称需要和 signals.yaml 里的 type 字段对应
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@register_source("custom_example")
class CustomExampleSource:
    """自定义信号源示例。"""

    def __init__(
        self,
        source_id: str,
        account_id: Optional[str] = None,
        **kwargs,
    ):
        """
        Args:
            source_id:  信号源ID（来自配置文件的 id 字段）
            account_id: 指定执行账号，None 表示按权重分配
            **kwargs:   配置文件中该信号源的其他自定义参数
                        例如配置了 api_url: "http://xxx"
                        这里就能通过 kwargs["api_url"] 拿到
        """
        self.source_id = source_id
        self.account_id = account_id
        # 你可以在这里读取额外配置参数
        # self.api_url = kwargs.get("api_url", "http://default")
        # self.threshold = kwargs.get("threshold", 0.5)

    def fetch_signals(self) -> list[TradingSignal]:
        """
        获取信号列表 —— 这里写你的核心策略逻辑。

        返回值：
            list[TradingSignal]，每个信号包含：
              - symbol:    标的代码，如 "600519.SH"
              - direction: 方向，SignalDirection.LONG / SHORT / NEUTRAL
              - strength:  信号强度 0~1，越大越强
              - source:    来源标识（用 self.source_id）
              - account_id: 指定账号（用 self.account_id）

        示例场景：
          - 从数据库查询最新信号
          - 调用外部 API 获取推荐
          - 读取本地 CSV/JSON 文件
          - 运行你自己的指标计算
        """

        # ══════════════════════════════════════
        # 在下面替换成你自己的信号逻辑
        # ══════════════════════════════════════

        signals = []

        # 示例：做多 600519.SH，强度 0.8
        signals.append(TradingSignal(
            symbol="600519.SH",
            direction=SignalDirection.LONG,
            strength=0.8,
            source=self.source_id,
            account_id=self.account_id,
            timestamp=time.time(),
        ))

        # 示例：做空 000858.SZ，强度 0.6
        signals.append(TradingSignal(
            symbol="000858.SZ",
            direction=SignalDirection.SHORT,
            strength=0.6,
            source=self.source_id,
            account_id=self.account_id,
            timestamp=time.time(),
        ))

        return signals
