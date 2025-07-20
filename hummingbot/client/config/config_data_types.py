from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode, model_json_schema

from hummingbot.client.config.config_validators import validate_connector


class ClientConfigEnum(Enum):
    def __str__(self):
        return self.value


# 统一规定Config对象的字段的额外数据
@dataclass()
class ClientFieldData:
    prompt: Optional[Callable[['BaseClientModel'], str]] = None
    prompt_on_new: bool = False
    is_secure: bool = False
    is_connect_key: bool = False
    is_updatable: bool = False


# 多个Config对象的基类，子类包括：
# ClientConfigMap, MQTTBridgeConfigMap, MarketDataCollectionConfigMap, ColorConfigMap, PaperTradeConfigMap, KillSwitchMode, DBMode, 
# GatewayConfigMap, GlobalTokenConfigMap, CommandsTimeoutConfigMap, AnonymizedMetricsMode, RateSourceModeBase, BaseConnectorConfigMap, 
# SSLConfigMap, BaseStrategyConfigMap, InjectiveFeeCalculatorMode, InjectiveNetworkMode, InjectiveAccountMode, InfiniteModel, 
# FromDateToDateModel, DailyBetweenTimesModel, SingleOrderLevelModel, MultiOrderLevelModel, TrackHangingOrdersModel, IgnoreHangingOrdersModel, 
# ConversionRateModel, OrderRefreshMode, EmptyMarketConfigMap, MarketConfigMap, StrategyV2ConfigBase, ControllerConfigBase, SimplePMMConfig, 
# VWAPConfig, SimpleXEMMConfig
class BaseClientModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, title=None, extra="forbid", json_encoders={
        datetime: lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"),
    })

    @classmethod
    def _clear_schema_cache(cls):
        cls.__schema_cache__ = {}

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = 'validation',
    ) -> dict[str, Any]:
        """Generates a JSON schema for a model class.

               Args:
                   by_alias: Whether to use attribute aliases or not.
                   ref_template: The reference template.
                   schema_generator: To override the logic used to generate the JSON schema, as a subclass of
                       `GenerateJsonSchema` with your desired modifications
                   mode: The mode in which to generate the schema.

               Returns:
                   The JSON schema for the given model class.
               """
        # Check if in json_schema_extra we have functions defined as values that can produce errors when serializing
        # the schema. We need to remove them.
        for key, value in cls.model_fields.items():
            if callable(value.json_schema_extra["prompt"]):
                value.json_schema_extra["prompt"] = value.json_schema_extra["prompt"](cls)
        return model_json_schema(
            cls, by_alias=by_alias, ref_template=ref_template, schema_generator=schema_generator, mode=mode
        )

    def is_required(self, attr: str) -> bool:
        default = self.__class__.model_fields[attr].default
        if (hasattr(self.__class__.model_fields[attr].annotation, "_name") and
                self.__class__.model_fields[attr].annotation._name != "Optional" and (default is None or default == Ellipsis)):
            return True
        else:
            return False


# ConnectorConfigMap基类，只有connector名称，其他key等字段由子类添加
class BaseConnectorConfigMap(BaseClientModel):
    connector: str = Field(
        default=...,
        json_schema_extra={
            "prompt": "What is your connector?",
            "prompt_on_new": True,
        },
    )

    @field_validator("connector", mode="before")
    @classmethod
    def validate_connector(cls, v: str):
        ret = validate_connector(v)
        if ret is not None:
            raise ValueError(ret)
        return v
