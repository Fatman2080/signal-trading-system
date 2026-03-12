# -*- coding: utf-8 -*-
"""定时调度器：后台线程周期性执行 run_cycle。"""
import time
import threading
import traceback
from pathlib import Path
from typing import Optional, Callable

from src.config_io import get_config_dir


class Scheduler:
    """后台定时调度器，周期性调用 run_cycle。"""

    def __init__(self, interval: float = 60.0):
        self._interval = interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_run_time: Optional[float] = None
        self._last_result: Optional[dict] = None
        self._total_runs = 0
        self._total_errors = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable] = []

    @property
    def running(self) -> bool:
        return self._running

    @property
    def interval(self) -> float:
        return self._interval

    @interval.setter
    def interval(self, value: float):
        self._interval = max(5.0, value)

    def add_listener(self, fn: Callable):
        self._listeners.append(fn)

    def _notify(self, event: str, data: dict):
        for fn in self._listeners:
            try:
                fn(event, data)
            except Exception:
                pass

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._notify("scheduler_started", {"interval": self._interval})

    def stop(self):
        if not self._running:
            return
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._notify("scheduler_stopped", {})

    def _loop(self):
        while not self._stop_event.is_set():
            self._execute_once()
            self._stop_event.wait(timeout=self._interval)

    def _execute_once(self):
        import io, sys
        from src.main import run_cycle
        from src import log_store

        config_dir = get_config_dir()
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = self._Tee(old_stdout, buf)
        try:
            order_ids = run_cycle(config_dir)
            logs = [l for l in buf.getvalue().splitlines() if l.strip()]
            log_store.append(logs, source="scheduler")
            log_store.trim()
            with self._lock:
                self._last_run_time = time.time()
                self._total_runs += 1
                self._last_result = {
                    "ok": True,
                    "order_count": len(order_ids),
                    "order_ids": order_ids,
                    "logs": logs,
                    "time": self._last_run_time,
                }
            self._notify("cycle_done", self._last_result)
        except Exception as e:
            logs = [l for l in buf.getvalue().splitlines() if l.strip()]
            log_store.append(logs + [f"[错误] {e}"], source="scheduler")
            with self._lock:
                self._last_run_time = time.time()
                self._total_errors += 1
                self._last_result = {
                    "ok": False,
                    "error": str(e),
                    "logs": logs,
                    "time": self._last_run_time,
                }
            self._notify("cycle_error", self._last_result)
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout

    class _Tee:
        def __init__(self, *streams):
            self._streams = streams
        def write(self, data):
            for s in self._streams:
                s.write(data)
        def flush(self):
            for s in self._streams:
                s.flush()

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "interval": self._interval,
                "total_runs": self._total_runs,
                "total_errors": self._total_errors,
                "last_run_time": self._last_run_time,
                "last_result": self._last_result,
            }


_global_scheduler: Optional[Scheduler] = None


def get_scheduler() -> Scheduler:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = Scheduler()
    return _global_scheduler
