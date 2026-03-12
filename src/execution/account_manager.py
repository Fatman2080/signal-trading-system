# -*- coding: utf-8 -*-
"""多账号管理：加载配置并创建经纪商连接（支持 API 凭证）。"""
import os
from dataclasses import dataclass, field
from typing import Optional

from .brokers.base import BrokerBase
from .brokers.sim import SimBroker


@dataclass
class AccountConfig:
    id: str
    name: str
    broker: str
    weight: float
    enabled: bool = True
    api_key: str = ""
    api_secret: str = ""
    extra: dict = field(default_factory=dict)


def _resolve_env(val: str) -> str:
    """如果值以 ${...} 包裹，从环境变量读取。"""
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        env_name = val[2:-1]
        return os.environ.get(env_name, "")
    return val or ""


# Broker 类型 → 工厂函数（延迟导入，避免未安装依赖时报错）
def _create_broker(broker_type: str, **kwargs) -> BrokerBase:
    if broker_type == "sim":
        return SimBroker(**kwargs)

    if broker_type in ("binance", "binance_futures"):
        from .brokers.binance_futures import BinanceFuturesBroker
        return BinanceFuturesBroker(**kwargs)

    if broker_type in ("hyperliquid", "hype", "hl"):
        from .brokers.hyperliquid_broker import HyperliquidBroker
        return HyperliquidBroker(**kwargs)

    raise ValueError(
        f"未知 Broker 类型: '{broker_type}'。"
        f"支持: sim, binance_futures, hyperliquid"
    )


class AccountManager:
    """根据配置创建各账号的 Broker 实例，将 api_key/api_secret 传递给 Broker。"""

    def __init__(self, accounts: list[dict]):
        self.configs: list[AccountConfig] = []
        self._clients: dict[str, BrokerBase] = {}
        for ac in accounts:
            if not ac.get("enabled", True):
                continue
            known_keys = {"id", "name", "broker", "weight", "enabled", "api_key", "api_secret"}
            extra = {k: v for k, v in ac.items() if k not in known_keys}
            cfg = AccountConfig(
                id=ac["id"],
                name=ac.get("name", ac["id"]),
                broker=ac.get("broker", "sim"),
                weight=float(ac.get("weight", 0.0)),
                enabled=True,
                api_key=_resolve_env(ac.get("api_key", "")),
                api_secret=_resolve_env(ac.get("api_secret", "")),
                extra=extra,
            )
            # extra 中的布尔值修正（YAML 读出来是 True/False，某些参数需要 bool）
            for k in ("testnet",):
                if k in cfg.extra and isinstance(cfg.extra[k], str):
                    cfg.extra[k] = cfg.extra[k].lower() in ("true", "1", "yes")
            self.configs.append(cfg)
        self._build_clients()

    def _build_clients(self) -> None:
        for cfg in self.configs:
            try:
                self._clients[cfg.id] = _create_broker(
                    cfg.broker,
                    account_id=cfg.id,
                    api_key=cfg.api_key,
                    api_secret=cfg.api_secret,
                    **cfg.extra,
                )
            except Exception as e:
                print(f"[AccountManager] 创建 Broker 失败 [{cfg.id}] ({cfg.broker}): {e}")

    def get_client(self, account_id: str) -> Optional[BrokerBase]:
        return self._clients.get(account_id)

    def get_all_clients(self) -> list[tuple[AccountConfig, BrokerBase]]:
        return [(c, self._clients[c.id]) for c in self.configs if c.id in self._clients]

    def get_weights(self) -> list[tuple[str, float]]:
        total = sum(c.weight for c in self.configs)
        if total <= 0:
            return [(c.id, 0.0) for c in self.configs]
        return [(c.id, c.weight / total) for c in self.configs]
