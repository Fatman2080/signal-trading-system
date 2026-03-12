# -*- coding: utf-8 -*-
"""Web 后端：配置 API + Webhook 接收 + 定时调度器。"""
import sys
import time
import secrets
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from flask import Flask, request, jsonify, send_from_directory

from src.config_io import get_config_dir, load_yaml, save_yaml
from src.signals.queue import get_signal_queue, parse_webhook_signals
from src.scheduler import get_scheduler

app = Flask(__name__, static_folder="web/static", static_url_path="/static")


def _load_webhook_config() -> dict:
    config_dir = get_config_dir()
    cfg = load_yaml(config_dir / "webhook.yaml")
    return cfg


def _get_webhook_secret() -> str:
    cfg = _load_webhook_config()
    return cfg.get("secret", "")


def get_full_config():
    config_dir = get_config_dir()
    accounts = load_yaml(config_dir / "accounts.yaml")
    signals = load_yaml(config_dir / "signals.yaml")
    strategy = load_yaml(config_dir / "strategy.yaml")
    risk = load_yaml(config_dir / "risk.yaml")
    webhook_cfg = load_yaml(config_dir / "webhook.yaml")
    return {
        "accounts": accounts.get("accounts", []),
        "signals": signals.get("sources", []),
        "aggregator": signals.get("aggregator", {}),
        "strategy": strategy.get("strategy", {}),
        "risk": risk,
        "webhook": {
            "secret": webhook_cfg.get("secret", ""),
            "ttl": webhook_cfg.get("ttl", 300),
            "scheduler_interval": webhook_cfg.get("scheduler_interval", 60),
        },
    }


@app.route("/")
def index():
    return send_from_directory("web", "index.html")


@app.route("/api/config", methods=["GET"])
def api_get_config():
    try:
        return jsonify(get_full_config())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def api_save_config():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "需要 JSON body"}), 400
        config_dir = get_config_dir()
        save_yaml(config_dir / "accounts.yaml", {"accounts": data.get("accounts", [])})
        save_yaml(config_dir / "signals.yaml", {
            "sources": data.get("signals", []),
            "aggregator": data.get("aggregator", {}),
        })
        save_yaml(config_dir / "strategy.yaml", {
            "strategy": data.get("strategy", {}),
        })
        if "risk" in data:
            save_yaml(config_dir / "risk.yaml", data["risk"])
        if "webhook" in data:
            existing_wh = load_yaml(config_dir / "webhook.yaml")
            existing_wh.update(data["webhook"])
            save_yaml(config_dir / "webhook.yaml", existing_wh)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run", methods=["POST"])
def api_run():
    import io, sys
    from src import log_store
    try:
        from src.main import run_cycle
        config_dir = get_config_dir()

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = _Tee(old_stdout, buf)
        try:
            order_ids = run_cycle(config_dir)
        finally:
            sys.stdout = old_stdout

        logs = [l for l in buf.getvalue().splitlines() if l.strip()]
        log_store.append(logs, source="manual")
        log_store.trim()
        return jsonify({
            "ok": True,
            "order_count": len(order_ids),
            "order_ids": order_ids,
            "logs": logs,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


class _Tee:
    """同时写入两个流。"""
    def __init__(self, *streams):
        self._streams = streams
    def write(self, data):
        for s in self._streams:
            s.write(data)
    def flush(self):
        for s in self._streams:
            s.flush()


# ─── Webhook 接收 ─────────────────────────────────
@app.route("/api/webhook", methods=["POST"])
def api_webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "需要 JSON body"}), 400

        expected_secret = _get_webhook_secret()
        if expected_secret:
            token = data.get("secret", "") or request.headers.get("X-Webhook-Secret", "")
            if not secrets.compare_digest(str(token), str(expected_secret)):
                return jsonify({"error": "认证失败"}), 403

        signals = parse_webhook_signals(data)
        if not signals:
            return jsonify({"error": "未解析到有效信号"}), 400

        queue = get_signal_queue()
        queue.push_many(signals)

        return jsonify({
            "ok": True,
            "received": len(signals),
            "queue_size": queue.size(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Webhook 状态与生成密钥 ───────────────────────
@app.route("/api/webhook/status", methods=["GET"])
def api_webhook_status():
    queue = get_signal_queue()
    return jsonify(queue.status())


@app.route("/api/webhook/generate-secret", methods=["POST"])
def api_generate_secret():
    new_secret = secrets.token_urlsafe(32)
    config_dir = get_config_dir()
    cfg = load_yaml(config_dir / "webhook.yaml")
    cfg["secret"] = new_secret
    save_yaml(config_dir / "webhook.yaml", cfg)
    return jsonify({"ok": True, "secret": new_secret})


# ─── 定时调度器 ───────────────────────────────────
@app.route("/api/scheduler/status", methods=["GET"])
def api_scheduler_status():
    scheduler = get_scheduler()
    return jsonify(scheduler.status())


@app.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    data = request.get_json(silent=True) or {}
    interval = float(data.get("interval", 60))
    scheduler = get_scheduler()
    scheduler.interval = interval
    scheduler.start()
    return jsonify({"ok": True, "status": scheduler.status()})


@app.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    scheduler = get_scheduler()
    scheduler.stop()
    return jsonify({"ok": True, "status": scheduler.status()})


# ─── 队列信号预览 ─────────────────────────────────
@app.route("/api/queue/peek", methods=["GET"])
def api_queue_peek():
    queue = get_signal_queue()
    signals = queue.peek()
    return jsonify({
        "count": len(signals),
        "signals": [
            {
                "symbol": s.symbol,
                "direction": s.direction.name,
                "strength": s.strength,
                "source": s.source,
                "account_id": s.account_id,
                "timestamp": s.timestamp,
            }
            for s in signals
        ],
    })


# ─── 持仓 & 余额查询 ─────────────────────────────
@app.route("/api/positions", methods=["GET"])
def api_positions():
    """查询所有已连接账号的持仓和余额。"""
    try:
        config_dir = get_config_dir()
        accounts_cfg = load_yaml(config_dir / "accounts.yaml")
        from src.execution.account_manager import AccountManager

        accounts_list = accounts_cfg.get("accounts", [])
        if not accounts_list:
            return jsonify({"accounts": []})

        manager = AccountManager(accounts_list)
        result = []
        for cfg, client in manager.get_all_clients():
            account_data = {
                "id": cfg.id,
                "name": cfg.name,
                "broker": cfg.broker,
                "positions": [],
                "balance": {},
                "error": None,
            }

            # 查询余额
            if hasattr(client, "get_balance"):
                try:
                    account_data["balance"] = client.get_balance()
                except Exception as e:
                    account_data["error"] = f"余额查询失败: {e}"

            # 查询持仓
            if hasattr(client, "get_positions"):
                try:
                    account_data["positions"] = client.get_positions()
                except Exception as e:
                    err = f"持仓查询失败: {e}"
                    account_data["error"] = (account_data["error"] or "") + " " + err

            result.append(account_data)

        return jsonify({"accounts": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 信号源测试 API ─────────────────────────────
@app.route("/api/signal/test", methods=["POST"])
def api_signal_test():
    """测试信号源代码：执行因子计算并返回最近 z-score 分布。"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "需要 JSON body"}), 400

        src_type = data.get("type", "inline_code")
        symbol = data.get("symbol", "BTC")
        interval = data.get("interval", "1h")
        code = data.get("code", "")
        factor_name = data.get("factor_name", "")
        z_threshold = float(data.get("z_threshold", 1.0))
        direction = int(data.get("direction", 1))

        from src.signals.sources import create_source

        kwargs = {
            "source_id": "__test__",
            "symbol": symbol,
            "interval": interval,
            "z_threshold": z_threshold,
        }

        if src_type == "inline_code":
            if not code.strip():
                return jsonify({"error": "未提供代码"}), 400
            kwargs["code"] = code
            kwargs["direction"] = direction
        elif src_type == "alpha_factor":
            kwargs["factor_name"] = factor_name

        source = create_source(src_type, **kwargs)
        signals = source.fetch_signals()

        # 额外获取 z-score 分布信息
        z_info = []
        try:
            from src.signals.sources.alpha_factor import _fetch_binance_klines
            df = _fetch_binance_klines(symbol, interval, 100)

            if src_type == "inline_code":
                from src.signals.sources.inline_code import _exec_code
                z_scores = _exec_code(code, df, direction)
            elif src_type == "alpha_factor":
                from src.signals.sources.alpha_factor import _load_factor, _run_factor
                factor = _load_factor(kwargs.get("factors_path", ""), factor_name)
                if not factor:
                    base = Path(__file__).resolve().parent
                    factor = _load_factor(str(base / "Alpha-X_Top20_Factors" / "factors.json"), factor_name)
                if factor:
                    z_scores = _run_factor(factor, df)
                else:
                    z_scores = None

            if z_scores is not None:
                for t, v in z_scores.tail(20).items():
                    v = float(v)
                    sig = ""
                    if v > z_threshold:
                        sig = "LONG"
                    elif v < -z_threshold:
                        sig = "SHORT"
                    z_info.append({
                        "time": str(t),
                        "z_score": round(v, 4),
                        "signal": sig,
                    })
        except Exception:
            pass

        sig_list = []
        for s in signals:
            sig_list.append({
                "symbol": s.symbol,
                "direction": s.direction.name,
                "strength": round(s.strength, 4),
                "extra": s.extra or {},
            })

        return jsonify({
            "ok": True,
            "signals": sig_list,
            "z_history": z_info,
            "signal_count": len(sig_list),
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ─── 因子列表 API ─────────────────────────────
@app.route("/api/factors", methods=["GET"])
def api_factors():
    """返回 factors.json 中所有可用因子的列表。"""
    try:
        import json as _json
        fp = Path(__file__).resolve().parent / "Alpha-X_Top20_Factors" / "factors.json"
        if not fp.exists():
            return jsonify({"factors": []})
        with open(fp) as f:
            factors = _json.load(f)
        result = []
        for fac in factors:
            result.append({
                "factor_name": fac["factor_name"],
                "description": fac.get("description", ""),
                "sharpe": round(fac.get("sharpe", 0), 2),
                "direction": fac.get("direction", 1),
            })
        return jsonify({"factors": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 交易历史 & 复盘 API ─────────────────────────
@app.route("/api/trades", methods=["GET"])
def api_trades():
    """返回交易历史记录和统计。"""
    try:
        from src.journal.trade_log import load_all, compute_stats
        records = load_all()
        stats = compute_stats(records)
        recent = list(reversed(records[-100:]))
        return jsonify({"records": recent, "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── 运行日志 API ─────────────────────────────────
@app.route("/api/logs", methods=["GET"])
def api_logs():
    """返回持久化的运行日志。"""
    from src import log_store
    limit = request.args.get("limit", 500, type=int)
    records = log_store.load_recent(limit)
    return jsonify({"logs": records})


@app.route("/api/logs/clear", methods=["POST"])
def api_logs_clear():
    from src import log_store
    log_store.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888, debug=True)
