from typing import Dict, Type

from hummingbot.connector.exchange_base import ExchangeBase
from hummingbot.data_feed.fundingrate_feed.binance_perpetual_fundingrates.binance_perpetual_fundingrates import (
    BinancePerpetualFundingRates,
)
from hummingbot.data_feed.fundingrate_feed.data_types import FundingRateConfig
from hummingbot.data_feed.fundingrate_feed.fundingrate_base import FundingRateBase
from hummingbot.data_feed.fundingrate_feed.okx_perpetual_fundingrates.okx_perpetual_fundingrates import (
    OkxPerpetualFundingRates,
)


class UnsupportedConnectorException(Exception):
    """
    Exception raised when an unsupported connector is requested.
    """

    def __init__(self, connector: str):
        message = f"The connector {connector} is not available. Please select another one."
        super().__init__(message)


class FundingRateFactory:
    """
    The FundingRateFactory class creates and returns a Funding Rate object based on the specified configuration.
    It uses a mapping of connector names to their respective Funding Rate object classes.
    """
    _fundingrate_map: Dict[str, Type[FundingRateBase]] = {
        "binance_perpetual": BinancePerpetualFundingRates,
        "okx_perpetual": OkxPerpetualFundingRates,
    }

    @classmethod
    def get_fundingrate(cls, fundingrate_config: FundingRateConfig, exchange: ExchangeBase) -> FundingRateBase:
        """
        Returns a Funding Rate object based on the specified configuration.

        :param fundingrate_config: FundingRateConfig
        :return: Instance of FundingRateBase or its subclass.
        :raises UnsupportedConnectorException: If the connector is not supported.
        """
        connector_class = cls._fundingrate_map.get(fundingrate_config.connector)
        if connector_class:
            return connector_class(
                exchange,
                fundingrate_config.trading_pairs,
                fundingrate_config.rest_api_update_interval,
                fundingrate_config.standardization_duration_hours
            )
        else:
            raise UnsupportedConnectorException(fundingrate_config.connector)
