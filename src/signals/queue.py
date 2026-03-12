# -*- coding: utf-8 -*-
"""信号队列：线程安全的内存信号缓存，供 Webhook 推送和 run_cycle 消费。"""
import time
import threading
from typing import Optional
from .base import TradingSignal, SignalDirection


class SignalQueue:
    """线程安全的信号队列，支持 TTL 过期。"""

    def __init__(self, ttl: float = 300.0):
        """
        Args:
            ttl: 信号存活时间（秒），超过后自动丢弃，默认 5 分钟
        """
        self._lock = threading.Lock()
        self._signals: list[tuple[float, TradingSignal]] = []  # (timestamp, signal)
        self._ttl = ttl
        self._total_received = 0

    def push(self, signal: TradingSignal) -> None:
        with self._lock:
            if signal.timestamp <= 0:
                signal.timestamp = time.time()
            self._signals.append((time.time(), signal))
            self._total_received += 1

    def push_many(self, signals: list[TradingSignal]) -> None:
        with self._lock:
            now = time.time()
            for s in signals:
                if s.timestamp <= 0:
                    s.timestamp = now
                self._signals.append((now, s))
                self._total_received += 1

    def drain(self) -> list[TradingSignal]:
        """取出所有未过期信号并清空队列。"""
        with self._lock:
            now = time.time()
            valid = [s for ts, s in self._signals if now - ts < self._ttl]
            self._signals.clear()
            return valid

    def peek(self) -> list[TradingSignal]:
        """查看当前队列中的信号（不消费）。"""
        with self._lock:
            now = time.time()
            return [s for ts, s in self._signals if now - ts < self._ttl]

    def size(self) -> int:
        with self._lock:
            now = time.time()
            return sum(1 for ts, _ in self._signals if now - ts < self._ttl)

    @property
    def total_received(self) -> int:
        return self._total_received

    def status(self) -> dict:
        with self._lock:
            now = time.time()
            valid = [(ts, s) for ts, s in self._signals if now - ts < self._ttl]
            return {
                "queue_size": len(valid),
                "total_received": self._total_received,
                "ttl": self._ttl,
            }


# 全局单例
_global_queue: Optional[SignalQueue] = None


def get_signal_queue(ttl: float = 300.0) -> SignalQueue:
    global _global_queue
    if _global_queue is None:
        _global_queue = SignalQueue(ttl=ttl)
    return _global_queue


def parse_webhook_signals(data: dict, default_source: str = "webhook") -> list[TradingSignal]:
    """将 Webhook JSON 解析为 TradingSignal 列表。

    期望格式：
    {
        "secret": "your_token",
        "source": "my_strategy",          // 可选，默认 "webhook"
        "account_id": "account_1",        // 可选，指定执行账号
        "signals": [
            {"symbol": "600519.SH", "direction": "long", "strength": 0.8},
            {"symbol": "000858.SZ", "direction": "short", "strength": 0.6}
        ]
    }
    """
    source = data.get("source", default_source)
    account_id = data.get("account_id")
    if account_id is not None and isinstance(account_id, str) and not account_id.strip():
        account_id = None

    raw_signals = data.get("signals", [])
    results = []
    dir_map = {
        "long": SignalDirection.LONG, "buy": SignalDirection.LONG, "1": SignalDirection.LONG,
        "short": SignalDirection.SHORT, "sell": SignalDirection.SHORT, "-1": SignalDirection.SHORT,
        "neutral": SignalDirection.NEUTRAL, "0": SignalDirection.NEUTRAL,
    }

    for s in raw_signals:
        if not isinstance(s, dict) or "symbol" not in s:
            continue
        dir_str = str(s.get("direction", "long")).lower().strip()
        direction = dir_map.get(dir_str, SignalDirection.LONG)
        strength = float(s.get("strength", 0.5))
        strength = max(0.0, min(1.0, strength))

        sig_account = s.get("account_id") or account_id

        extra = s.get("extra")
        if extra is not None and not isinstance(extra, dict):
            extra = None

        results.append(TradingSignal(
            symbol=s["symbol"],
            direction=direction,
            strength=strength,
            source=source,
            account_id=sig_account,
            timestamp=time.time(),
            extra=extra,
        ))

    return results
