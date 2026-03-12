# -*- coding: utf-8 -*-
"""运行日志持久化：追加写入 JSONL，提供读取与清理。"""
import json
import time
import threading
from pathlib import Path

_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "run_logs.jsonl"
_MAX_LINES = 2000
_lock = threading.Lock()


def _ensure_dir():
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def append(lines: list[str], source: str = "system") -> None:
    """追加一批日志行，每行存为 {ts, source, text}。"""
    if not lines:
        return
    _ensure_dir()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(
                    {"ts": now, "source": source, "text": line},
                    ensure_ascii=False,
                ) + "\n")


def load_recent(limit: int = 500) -> list[dict]:
    """读取最近 limit 条日志。"""
    if not _LOG_PATH.exists():
        return []
    with _lock:
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    result = []
    for raw in all_lines[-limit:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            result.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return result


def trim() -> None:
    """保留最近 _MAX_LINES 条，删除旧日志。"""
    if not _LOG_PATH.exists():
        return
    with _lock:
        with open(_LOG_PATH, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        if len(all_lines) <= _MAX_LINES:
            return
        with open(_LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(all_lines[-_MAX_LINES:])


def clear() -> None:
    """清空所有日志。"""
    with _lock:
        if _LOG_PATH.exists():
            _LOG_PATH.write_text("", encoding="utf-8")
