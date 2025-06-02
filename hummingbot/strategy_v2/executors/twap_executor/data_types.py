from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import field_validator

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.data_types import ExecutorConfigBase


class TWAPMode(Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"


class TWAPExecutorConfig(ExecutorConfigBase):
    type: Literal["twap_executor"] = "twap_executor"
    connector_name: str
    trading_pair: str
    side: TradeType
    leverage: int = 1
    total_amount_quote: Decimal
    # 下单期间总时长
    total_duration: int
    # 下单间隔时间
    order_interval: int
    mode: TWAPMode = TWAPMode.TAKER

    # MAKER mode specific parameters
    # 下限价单的价格buffer，即要多少价格优势
    limit_order_buffer: Optional[Decimal] = None
    # 下限价单的订单刷新时间，即过多久就重下限价单
    order_resubmission_time: Optional[int] = None

    @field_validator('limit_order_buffer', mode="before")
    @classmethod
    def validate_limit_order_buffer(cls, v, values):
        if v is None and values["mode"] == TWAPMode.MAKER:
            raise ValueError("limit_order_buffer is required for MAKER mode")
        return v

    @property
    def is_maker(self) -> bool:
        return self.mode == TWAPMode.MAKER

    @property
    def number_of_orders(self) -> int:
        return (self.total_duration // self.order_interval) + 1

    @property
    def order_amount_quote(self) -> Decimal:
        return self.total_amount_quote / self.number_of_orders

    @property
    def order_type(self) -> OrderType:
        return OrderType.LIMIT if self.is_maker else OrderType.MARKET
