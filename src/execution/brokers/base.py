# -*- coding: utf-8 -*-
"""券商/交易所适配器基类。"""
from abc import ABC, abstractmethod
from typing import Optional


class BrokerBase(ABC):
    """抽象经纪商接口，便于对接 CTP、易盛、模拟盘等。"""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: Optional[float] = None,
    ) -> str:
        """下单，返回订单 id。"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单。"""
        pass

    @abstractmethod
    def get_account_id(self) -> str:
        """返回该连接对应的账号 id。"""
        pass
