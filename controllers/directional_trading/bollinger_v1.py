from typing import List

import pandas_ta as ta  # noqa: F401
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)


class BollingerV1ControllerConfig(DirectionalTradingControllerConfigBase):
    controller_name: str = "bollinger_v1"
    candles_config: List[CandlesConfig] = []
    candles_connector: str = Field(
        default=None,
        json_schema_extra={
            "prompt": "Enter the connector for the candles data, leave empty to use the same exchange as the connector: ",
            "prompt_on_new": True})
    candles_trading_pair: str = Field(
        default=None,
        json_schema_extra={
            "prompt": "Enter the trading pair for the candles data, leave empty to use the same trading pair as the connector: ",
            "prompt_on_new": True})
    interval: str = Field(
        default="3m",
        json_schema_extra={
            "prompt": "Enter the candle interval (e.g., 1m, 5m, 1h, 1d): ",
            "prompt_on_new": True})
    bb_length: int = Field(
        default=100,
        json_schema_extra={"prompt": "Enter the Bollinger Bands length: ", "prompt_on_new": True})
    bb_std: float = Field(default=2.0)
    bb_long_threshold: float = Field(default=0.0)
    bb_short_threshold: float = Field(default=1.0)

    @field_validator("candles_connector", mode="before")
    @classmethod
    def set_candles_connector(cls, v, validation_info: ValidationInfo):
        if v is None or v == "":
            return validation_info.data.get("connector_name")
        return v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def set_candles_trading_pair(cls, v, validation_info: ValidationInfo):
        if v is None or v == "":
            return validation_info.data.get("trading_pair")
        return v


class BollingerV1Controller(DirectionalTradingControllerBase):
    def __init__(self, config: BollingerV1ControllerConfig, *args, **kwargs):
        self.config = config
        self.max_records = self.config.bb_length
        if len(self.config.candles_config) == 0:
            self.config.candles_config = [CandlesConfig(
                connector=config.candles_connector,
                trading_pair=config.candles_trading_pair,
                interval=config.interval,
                max_records=self.max_records
            )]
        super().__init__(config, *args, **kwargs)

    # 此方法根据行情生成signal，基类的create_actions_proposal方法随后根据signal创建新Executor(默认PositionExecutor)
    async def update_processed_data(self):
        # 获取max_records条candle记录，布林带计算需要
        df = self.market_data_provider.get_candles_df(connector_name=self.config.candles_connector,
                                                      trading_pair=self.config.candles_trading_pair,
                                                      interval=self.config.interval,
                                                      max_records=self.max_records)
        # Add indicators
        # 加指标列到df上
        df.ta.bbands(length=self.config.bb_length, std=self.config.bb_std, append=True)
        # 加到df上的新列
        bbp = df[f"BBP_{self.config.bb_length}_{self.config.bb_std}"]

        # Generate signal
        long_condition = bbp < self.config.bb_long_threshold
        short_condition = bbp > self.config.bb_short_threshold

        # Generate signal
        # 加signal列
        df["signal"] = 0
        # 指标满足做多条件，signal列置为1
        df.loc[long_condition, "signal"] = 1
        # 指标满足做空条件，signal列置为-1
        df.loc[short_condition, "signal"] = -1

        # Update processed data
        # 取最新的一个signal值
        self.processed_data["signal"] = df["signal"].iloc[-1]
        # 用于状态更新(to_format_status)
        self.processed_data["features"] = df
