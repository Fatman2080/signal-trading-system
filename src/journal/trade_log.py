# -*- coding: utf-8 -*-
"""交易日志持久化：每笔开仓/平仓记录写入 JSONL 文件。"""
import json
import time
import threading
from pathlib import Path
from typing import Optional


_lock = threading.Lock()


def _get_log_path() -> Path:
    p = Path(__file__).resolve().parent.parent.parent / "data" / "trades.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log_open(
    order_id: str,
    account_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: Optional[float],
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    signal_source: str = "",
    signal_reasons: Optional[list] = None,
    signal_strength: float = 0.0,
    extra: Optional[dict] = None,
) -> dict:
    """记录一笔开仓。"""
    record = {
        "id": order_id,
        "type": "open",
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timestamp": time.time(),
        "account_id": account_id,
        "symbol": symbol.upper(),
        "side": side,
        "quantity": quantity,
        "price": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "signal_source": signal_source,
        "signal_reasons": signal_reasons or [],
        "signal_strength": signal_strength,
        "status": "open",
        "extra": extra or {},
    }
    _append(record)
    return record


def log_close(
    order_id: str,
    account_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: Optional[float],
    close_reason: str = "",
    related_open_id: str = "",
) -> dict:
    """记录一笔平仓。"""
    record = {
        "id": order_id,
        "type": "close",
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timestamp": time.time(),
        "account_id": account_id,
        "symbol": symbol.upper(),
        "side": side,
        "quantity": quantity,
        "price": price,
        "close_reason": close_reason,
        "related_open_id": related_open_id,
        "status": "closed",
    }
    _append(record)
    return record


def _append(record: dict) -> None:
    with _lock:
        with open(_get_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_all() -> list[dict]:
    """加载所有交易记录。"""
    path = _get_log_path()
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def load_open_trades() -> list[dict]:
    """加载所有状态为 open 的交易。"""
    return [r for r in load_all() if r.get("status") == "open" and r.get("type") == "open"]


def compute_stats(records: list[dict]) -> dict:
    """计算复盘统计指标。"""
    opens = {r["id"]: r for r in records if r.get("type") == "open"}
    closes = [r for r in records if r.get("type") == "close"]

    trades = []
    for c in closes:
        open_id = c.get("related_open_id", "")
        o = opens.get(open_id)
        if not o or not o.get("price") or not c.get("price"):
            continue
        is_long = o["side"].lower() in ("buy", "long")
        if is_long:
            pnl = (c["price"] - o["price"]) * c["quantity"]
        else:
            pnl = (o["price"] - c["price"]) * c["quantity"]
        pnl_pct = pnl / (o["price"] * o["quantity"]) * 100 if o["price"] > 0 else 0
        trades.append({"pnl": pnl, "pnl_pct": pnl_pct, "symbol": o["symbol"]})

    if not trades:
        return {
            "total_trades": len(opens),
            "closed_trades": 0,
            "open_trades": len(load_open_trades()),
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl_pct": 0,
            "best_trade": 0,
            "worst_trade": 0,
        }

    wins = [t for t in trades if t["pnl"] > 0]
    total_pnl = sum(t["pnl"] for t in trades)

    return {
        "total_trades": len(opens),
        "closed_trades": len(trades),
        "open_trades": len(load_open_trades()),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 2),
        "best_trade": round(max(t["pnl"] for t in trades), 2),
        "worst_trade": round(min(t["pnl"] for t in trades), 2),
    }
