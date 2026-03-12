# -*- coding: utf-8 -*-
"""信号源注册表：根据配置中的 type 字段自动加载对应的信号源类。"""
from typing import Optional

from ..base import TradingSignal

# 信号源注册表：type名称 → 信号源类
_REGISTRY: dict[str, type] = {}


def register_source(type_name: str):
    """装饰器：将信号源类注册到全局表中。

    用法：
        @register_source("my_strategy")
        class MySignalSource:
            def __init__(self, source_id, account_id=None, **kwargs): ...
            def fetch_signals(self) -> list[TradingSignal]: ...
    """
    def decorator(cls):
        _REGISTRY[type_name] = cls
        return cls
    return decorator


def create_source(
    type_name: str,
    source_id: str,
    account_id: Optional[str] = None,
    **kwargs,
):
    """根据 type 名称创建信号源实例。

    Args:
        type_name: 配置中的 type 字段，如 "dummy", "my_strategy"
        source_id: 信号源 ID
        account_id: 指定执行账号，None 表示按权重分配
        **kwargs: 传递给信号源构造函数的额外参数
    """
    cls = _REGISTRY.get(type_name)
    if cls is None:
        available = ', '.join(_REGISTRY.keys()) or '无'
        raise ValueError(
            f"未知信号源类型: '{type_name}'。"
            f"已注册的类型: {available}。"
            f"请在 src/signals/sources/ 下创建信号源并用 @register_source('{type_name}') 注册。"
        )
    return cls(source_id=source_id, account_id=account_id, **kwargs)


def list_source_types() -> list[str]:
    """返回所有已注册的信号源类型名称。"""
    return list(_REGISTRY.keys())
