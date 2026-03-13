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


def find_open_trade(symbol: str, account_id: str) -> Optional[dict]:
    """查找指定币种和账号的最近一笔未平仓开仓记录。"""
    records = load_all()
    closed_ids = {r.get("related_open_id") for r in records if r.get("type") == "close" and r.get("related_open_id")}
    for r in reversed(records):
        if (r.get("type") == "open"
                and r.get("symbol", "").upper() == symbol.upper()
                and r.get("account_id") == account_id
                and r.get("status") == "open"
                and r["id"] not in closed_ids):
            return r
    return None


def mark_closed(open_id: str) -> None:
    """将指定开仓记录标记为已平仓（重写文件中对应行）。"""
    path = _get_log_path()
    if not path.exists():
        return
    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()
        updated = []
        for line in lines:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                updated.append(line)
                continue
            if r.get("id") == open_id and r.get("type") == "open":
                r["status"] = "closed"
            updated.append(json.dumps(r, ensure_ascii=False))
        path.write_text("\n".join(updated) + "\n", encoding="utf-8")


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
    """记录一笔平仓，自动关联最近的开仓记录。"""
    if not related_open_id:
        open_trade = find_open_trade(symbol, account_id)
        if open_trade:
            related_open_id = open_trade["id"]

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

    if related_open_id:
        mark_closed(related_open_id)

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


def sync_positions(exchange_positions: list[dict]) -> list[dict]:
    """将交易所实际持仓与日志对比，自动补录已消失的持仓为平仓。

    参数:
        exchange_positions: [{"symbol": "BTC", "side": "SHORT", "account_id": "hype_01", "price": 70000}, ...]

    返回:
        被自动平仓的记录列表
    """
    open_trades = load_open_trades()
    if not open_trades:
        return []

    live_keys = set()
    price_map = {}
    for p in exchange_positions:
        sym = p.get("symbol", "").upper()
        acc = p.get("account_id", "")
        key = f"{sym}:{acc}"
        live_keys.add(key)
        price_map[sym] = p.get("price", 0)

    closed = []
    for trade in open_trades:
        sym = trade.get("symbol", "").upper()
        acc = trade.get("account_id", "")
        key = f"{sym}:{acc}"
        if key not in live_keys:
            is_long = trade["side"].lower() in ("buy", "long")
            close_side = "sell" if is_long else "buy"
            close_price = price_map.get(sym) or trade.get("price", 0)
            r = log_close(
                order_id=f"sync_{int(time.time()*1000)}_{sym}",
                account_id=acc,
                symbol=sym,
                side=close_side,
                quantity=trade.get("quantity", 0),
                price=close_price,
                close_reason="TP/SL触发或交易所平仓",
                related_open_id=trade["id"],
            )
            closed.append(r)
            print(f"[持仓同步] {sym} 已不在交易所持仓中，自动标记平仓")

    return closed


def compute_stats(records: list[dict]) -> dict:
    """计算复盘统计指标。支持按 related_open_id 匹配，也支持按 symbol+account 回退匹配。"""
    opens = [r for r in records if r.get("type") == "open"]
    closes = [r for r in records if r.get("type") == "close"]
    opens_by_id = {r["id"]: r for r in opens}

    trades = []
    matched_open_ids = set()

    for c in closes:
        o = None
        open_id = c.get("related_open_id", "")
        if open_id and open_id in opens_by_id:
            o = opens_by_id[open_id]
        else:
            sym = c.get("symbol", "").upper()
            acc = c.get("account_id", "")
            close_ts = c.get("timestamp", 0)
            candidates = [
                r for r in opens
                if r.get("symbol", "").upper() == sym
                and r.get("account_id") == acc
                and r["id"] not in matched_open_ids
                and r.get("timestamp", 0) < close_ts
            ]
            if candidates:
                o = max(candidates, key=lambda r: r.get("timestamp", 0))

        if not o or not o.get("price") or not c.get("price"):
            continue

        matched_open_ids.add(o["id"])
        is_long = o["side"].lower() in ("buy", "long")
        if is_long:
            pnl = (c["price"] - o["price"]) * c["quantity"]
        else:
            pnl = (o["price"] - c["price"]) * c["quantity"]
        pnl_pct = pnl / (o["price"] * o["quantity"]) * 100 if o["price"] > 0 else 0
        trades.append({"pnl": pnl, "pnl_pct": pnl_pct, "symbol": o["symbol"]})

    open_count = sum(1 for r in opens if r.get("status") == "open")

    if not trades:
        return {
            "total_trades": len(opens),
            "closed_trades": 0,
            "open_trades": open_count,
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
        "open_trades": open_count,
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 2),
        "best_trade": round(max(t["pnl"] for t in trades), 2),
        "worst_trade": round(min(t["pnl"] for t in trades), 2),
    }
