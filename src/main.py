# -*- coding: utf-8 -*-
"""主流程：多信号采集 -> 聚合 -> 策略生成订单 -> 风控(持仓感知) -> 平仓+开仓。"""
from pathlib import Path

from src.config_io import load_yaml
from src.signals.base import TradingSignal
from src.signals.aggregator import SignalAggregator
from src.signals.sources import create_source
from src.signals.queue import get_signal_queue
from src.strategy.engine import StrategyEngine
from src.risk.order_validate import OrderValidator, PositionInfo
from src.execution.account_manager import AccountManager
from src.execution.executor import MultiAccountExecutor
from src.execution.order_types import PendingOrder


def run_cycle(
    config_dir: Path,
) -> list[str]:
    config_dir = Path(config_dir)
    accounts_cfg = load_yaml(config_dir / "accounts.yaml")
    signals_cfg = load_yaml(config_dir / "signals.yaml")
    strategy_cfg = load_yaml(config_dir / "strategy.yaml")
    risk_cfg = load_yaml(config_dir / "risk.yaml")

    # 1. 多账号
    accounts_list = accounts_cfg.get("accounts", [])
    account_manager = AccountManager(accounts_list)
    dry_run = risk_cfg.get("dry_run", False)
    executor = MultiAccountExecutor(account_manager, dry_run=dry_run)

    # 1b. 持仓同步：对比交易所实际持仓，自动补录已消失的仓位
    _sync_exchange_positions(account_manager)

    # 2. 信号源（根据配置 type 字段自动加载对应信号源类）
    sources_cfg = signals_cfg.get("sources", [])
    source_weights = {s["id"]: float(s.get("weight", 0.5)) for s in sources_cfg}

    source_weights["__webhook__"] = 1.0

    aggregator = SignalAggregator(
        source_weights=source_weights,
        min_strength=float(signals_cfg.get("aggregator", {}).get("min_strength", 0.3)),
    )

    raw_signals: list[TradingSignal] = []

    # 2a. 从信号队列消费 Webhook 推送的信号
    queue = get_signal_queue()
    webhook_signals = queue.drain()
    if webhook_signals:
        for ws in webhook_signals:
            if ws.source not in source_weights:
                source_weights[ws.source] = 1.0
        raw_signals.extend(webhook_signals)
        print(f"[webhook] 从队列获取 {len(webhook_signals)} 条信号")

    # 2b. 内置信号源
    for sc in sources_cfg:
        src_id = sc["id"]
        src_type = sc.get("type", "dummy")
        if src_type == "webhook":
            continue
        acc_id = sc.get("account_id")
        if acc_id is not None and isinstance(acc_id, str) and acc_id.strip() == "":
            acc_id = None
        extra = {k: v for k, v in sc.items() if k not in ("id", "type", "account_id", "weight")}
        source = create_source(src_type, source_id=src_id, account_id=acc_id, **extra)
        raw_signals.extend(source.fetch_signals())

    # 3. 多信号聚合
    aggregated = aggregator.aggregate(raw_signals)

    # 4. 策略：信号 -> 订单（保留 account_id）
    strategy_params = strategy_cfg.get("strategy", {})
    qty = float(strategy_params.get("quantity_per_signal", 0.01))
    engine = StrategyEngine(
        order_type=strategy_params.get("default_order_type", "market"),
        default_price=0.0,
    )
    pending_orders = engine.signals_to_orders(
        aggregated,
        quantity_per_signal=qty,
    )

    # 4b. 补充止盈止损默认值
    tp_sl_cfg = risk_cfg.get("tp_sl", {})
    if tp_sl_cfg.get("enabled", True):
        _apply_default_tp_sl(pending_orders, tp_sl_cfg)

    if not pending_orders:
        print("[主流程] 本轮无待执行订单")
        return []

    # 5. 查询账户状态（余额 + 持仓 + 价格）
    total_equity = _query_total_equity(account_manager)
    positions = _query_all_positions(account_manager)
    prices = _query_prices(pending_orders, account_manager)

    _fill_market_prices(pending_orders, prices)

    # 6. 风控过滤（持仓感知）
    validator = OrderValidator(
        allowed_symbols=strategy_params.get("symbols") or None,
        max_single_order_pct=risk_cfg.get("max_single_order_pct"),
        max_position_pct=risk_cfg.get("max_position_pct"),
        max_total_exposure_pct=risk_cfg.get("max_total_exposure_pct"),
        max_daily_trades=risk_cfg.get("max_daily_trades"),
        reverse_close=risk_cfg.get("reverse_close", True),
        allow_add_position=risk_cfg.get("allow_add_position", False),
    )

    close_orders, open_orders = validator.filter_orders(
        pending_orders,
        total_equity=total_equity,
        positions=positions,
        prices=prices,
    )

    # 7. 执行：先平仓，再开仓，同时记录交易日志
    from src.journal.trade_log import log_open, log_close

    order_ids: list[str] = []

    if close_orders:
        print(f"[主流程] 执行 {len(close_orders)} 笔平仓单")
        close_ids = executor.execute_orders(close_orders)
        order_ids.extend(close_ids)
        for filled in executor.filled_orders:
            log_close(
                order_id=filled["order_id"],
                account_id=filled["account_id"],
                symbol=filled["symbol"],
                side=filled["side"],
                quantity=filled["quantity"],
                price=filled["price"],
                close_reason="反向信号平仓",
            )
        executor.filled_orders.clear()

    if open_orders:
        print(f"[主流程] 执行 {len(open_orders)} 笔开仓单")
        open_ids = executor.execute_orders(open_orders)
        order_ids.extend(open_ids)
        for filled in executor.filled_orders:
            extra = filled.get("extra", {})
            log_open(
                order_id=filled["order_id"],
                account_id=filled["account_id"],
                symbol=filled["symbol"],
                side=filled["side"],
                quantity=filled["quantity"],
                price=filled["price"],
                stop_loss=filled.get("stop_loss"),
                take_profit=filled.get("take_profit"),
                signal_source=extra.get("signal_source", ""),
                signal_reasons=extra.get("reasons", []),
                signal_strength=0,
                extra=extra,
            )
        executor.filled_orders.clear()

    if not close_orders and not open_orders:
        print("[主流程] 所有订单被风控过滤，本轮无执行")

    return order_ids


def _query_total_equity(account_manager: AccountManager) -> float:
    """汇总所有账号的可用权益。"""
    total = 0.0
    for cfg, client in account_manager.get_all_clients():
        if not hasattr(client, "get_balance"):
            continue
        try:
            bal = client.get_balance()
            if isinstance(bal, dict):
                if "available" in bal:
                    total += float(bal["available"])
                elif "account_value" in bal:
                    total += float(bal["account_value"])
                else:
                    for asset_info in bal.values():
                        if isinstance(asset_info, dict):
                            total += float(asset_info.get("available", 0))
        except Exception as e:
            print(f"[风控] 查询余额失败 [{cfg.id}]: {e}")
    return total


def _query_all_positions(account_manager: AccountManager) -> list[PositionInfo]:
    """查询所有账号的持仓，转为 PositionInfo 列表。"""
    result: list[PositionInfo] = []
    for cfg, client in account_manager.get_all_clients():
        if not hasattr(client, "get_positions"):
            continue
        try:
            raw = client.get_positions()
            for p in raw:
                price = float(p.get("entry_price", 0))
                size = float(p.get("size", 0))
                result.append(PositionInfo(
                    symbol=p.get("symbol", ""),
                    side=p.get("side", ""),
                    size=size,
                    entry_price=price,
                ))
        except Exception as e:
            print(f"[风控] 查询持仓失败 [{cfg.id}]: {e}")
    return result


def _query_prices(orders: list[PendingOrder], account_manager: AccountManager) -> dict[str, float]:
    """批量查询订单涉及币种的当前价格。"""
    symbols = {o.symbol.upper() for o in orders}
    prices: dict[str, float] = {}
    for _cfg, client in account_manager.get_all_clients():
        if not hasattr(client, "get_price"):
            continue
        for sym in symbols:
            if sym in prices:
                continue
            try:
                px = client.get_price(sym)
                if px > 0:
                    prices[sym] = px
            except Exception:
                continue
    return prices


def _fill_market_prices(orders: list[PendingOrder], prices: dict[str, float]) -> None:
    """为市价单填充当前价格。"""
    for order in orders:
        if order.price is not None and order.price > 0:
            continue
        px = prices.get(order.symbol.upper(), 0)
        if px > 0:
            order.price = px


def _apply_default_tp_sl(orders: list[PendingOrder], tp_sl_cfg: dict) -> None:
    """为没有止盈止损的订单填充默认值（基于配置的百分比）。"""
    use_signal = tp_sl_cfg.get("use_signal_levels", True)
    default_sl_pct = tp_sl_cfg.get("default_sl_pct", 0)
    default_tp_pct = tp_sl_cfg.get("default_tp_pct", 0)

    for o in orders:
        if use_signal and o.stop_loss and o.take_profit:
            continue

        entry = o.price or o.extra.get("entry_price", 0)
        if not entry or entry <= 0:
            continue

        is_long = o.side.lower() in ("buy", "long")

        if not o.stop_loss and default_sl_pct > 0:
            o.stop_loss = entry * (1 - default_sl_pct) if is_long else entry * (1 + default_sl_pct)

        if not o.take_profit and default_tp_pct > 0:
            o.take_profit = entry * (1 + default_tp_pct) if is_long else entry * (1 - default_tp_pct)


def _sync_exchange_positions(account_manager: AccountManager) -> None:
    """对比交易所持仓与日志，自动补录已消失的仓位为平仓。"""
    from src.journal.trade_log import sync_positions, load_open_trades

    open_trades = load_open_trades()
    if not open_trades:
        return

    exchange_positions: list[dict] = []
    for cfg, client in account_manager.get_all_clients():
        if not hasattr(client, "get_positions"):
            continue
        try:
            for p in client.get_positions():
                exchange_positions.append({
                    "symbol": p.get("symbol", ""),
                    "side": p.get("side", ""),
                    "account_id": cfg.id,
                    "price": float(p.get("entry_price", 0)),
                })
        except Exception:
            pass

    sync_positions(exchange_positions)


def main() -> None:
    base = Path(__file__).resolve().parent
    config_dir = base.parent / "config"
    run_cycle(config_dir)


if __name__ == "__main__":
    main()
