from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import PositionAction, TradeType
from hummingbot.strategy_v2.executors.data_types import ExecutorConfigBase

# 下单策略对应的价值设置:
# LIMIT - 配置的价格
# LIMIT MAKER - 配置的价格与市场价(买一/卖一, 非中间价)的更优者
# MARKET - 无
# LIMIT CHASER - 按LimitChaserConfig动态控制
class ExecutionStrategy(Enum):
    LIMIT = "LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"
    MARKET = "MARKET"
    LIMIT_CHASER = "LIMIT_CHASER"


# limit chaser动态调整限价单来捕捉最佳交易机会(趋势跟踪策略中，通过在趋势中捕捉回撤来优化建仓成本)
class LimitChaserConfig(BaseModel):
    # 下单价与市场价的距离
    distance: Decimal
    # 市场价沿趋势行进，导致下单价与市场价的距离拉大后，如果超过市场价的一定比例则重新下单(依然按distance设置下单价)
    refresh_threshold: Decimal


class OrderExecutorConfig(ExecutorConfigBase):
    type: Literal["order_executor"] = "order_executor"
    trading_pair: str
    connector_name: str
    side: TradeType
    amount: Decimal
    position_action: PositionAction = PositionAction.OPEN
    price: Optional[Decimal] = None  # Required for LIMIT and LIMIT_MAKER
    chaser_config: Optional[LimitChaserConfig] = None  # Required for LIMIT_CHASER
    execution_strategy: ExecutionStrategy
    leverage: int = 1
    level_id: Optional[str] = None

    @field_validator("execution_strategy", mode="before")
    @classmethod
    def validate_execution_strategy(cls, value, validation_info: ValidationInfo):
        if value in [ExecutionStrategy.LIMIT, ExecutionStrategy.LIMIT_MAKER]:
            if validation_info.data.get('price') is None:
                raise ValueError("Price is required for LIMIT and LIMIT_MAKER execution strategies")
        elif value == ExecutionStrategy.LIMIT_CHASER:
            if validation_info.data.get('chaser_config') is None:
                raise ValueError("Chaser config is required for LIMIT_CHASER execution strategy")
        return value
