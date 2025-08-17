import asyncio
import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.connector.derivative.binance_perpetual.binance_perpetual_derivative import BinancePerpetualDerivative
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.data_feed.fundingrate_feed.binance_perpetual_fundingrates import constants as CONSTANTS
from hummingbot.data_feed.fundingrate_feed.fundingrate_base import FundingRateBase
from hummingbot.logger import HummingbotLogger


class BinancePerpetualFundingRates(FundingRateBase):
    """
    Binance specific implementation for funding rate data feed.
    """
    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(
        self,
        exchange: BinancePerpetualDerivative,
        trading_pairs: Optional[List[str]],
        update_interval: float = 10.0,
        standardization_duration_hours: int = 24,
    ):
        super().__init__(exchange, trading_pairs, update_interval, standardization_duration_hours)
        self._funding_interval_hours: Dict[str, int] = {}

    @property
    def name(self):
        return "binance_perpetual_fundingrates"

    @property
    def health_check_url(self):
        return self.rest_url + CONSTANTS.HEALTH_CHECK_ENDPOINT

    @property
    def rest_url(self):
        return CONSTANTS.REST_URL

    @property
    def fundingrate_endpoint(self):
        return CONSTANTS.MARK_PRICE_URL

    @property
    def fundingrate_url(self):
        return self.rest_url + CONSTANTS.MARK_PRICE_URL

    @property
    def funding_info_endpoint(self):
        return CONSTANTS.FUNDING_INFO_URL

    @property
    def funding_info_url(self):
        return self.rest_url + CONSTANTS.FUNDING_INFO_URL

    @property
    def _funding_info_rest_throttler_limit_id(self):
        return self.fundingrate_endpoint

    @property
    def wss_url(self):
        return CONSTANTS.WSS_URL

    @property
    def rate_limits(self):
        return CONSTANTS.RATE_LIMITS

    async def check_network(self) -> NetworkStatus:
        rest_assistant = await self._api_factory.get_rest_assistant()
        await rest_assistant.execute_request(
            url=self.health_check_url, throttler_limit_id=CONSTANTS.HEALTH_CHECK_ENDPOINT
        )
        return NetworkStatus.CONNECTED

    async def fetch_fundingrates_loop(self):
        while True:
            try:
                await self._fetch_funding_info()
                await self.fetch_fundingrates()
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                self.logger().info(f"Error fetching new funding rates from {self.rest_url}: {ex}")
                # self.logger().network(f"Error fetching new funding rates from {self.rest_url}.", exc_info=True,
                #                       app_warning_msg=f"Couldn't fetch newest funding rates from {self.name}. "
                #                                       "Check network connection.")

            delta = self._rest_update_interval - time.time() % self._rest_update_interval
            await self._sleep(delta)

    async def _fetch_funding_info(self):
        try:
            rest_assistant = await self._api_factory.get_rest_assistant()
            funding_info = await rest_assistant.execute_request(
                url=self.funding_info_url,
                throttler_limit_id=self._funding_info_rest_throttler_limit_id,
                method=self._rest_method,
            )
            self._funding_interval_hours = self._parse_rest_funding_info(funding_info)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            self.logger().info(f"Error fetching funding info from {self.funding_info_url}: {ex}")
            # self.logger().network(f"Error fetching funding info from {self.funding_info_url}.", exc_info=True,
            #                       app_warning_msg=f"Couldn't fetch newest funding info from {self.name}. "
            #                                       "Check network connection.")

    def _parse_rest_funding_info(self, data: Dict) -> Dict[str, int]:
        return {str(row["symbol"]): int(row["fundingIntervalHours"]) for row in data}

    def _get_rest_fundingrate_params(self) -> Optional[dict]:
        """
        为减少rest api request数量, 不传symbol参数, 直接全部获取
        For API documentation, please refer to:
        https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price
        """
        # params = {
        #     "symbol": self._ex_trading_pair,
        # }
        return None

    def _parse_rest_fundingrates(self, data: Dict) -> Dict[str, Decimal]:
        fr: Dict[str, Decimal] = {}
        for row in data:
            if row["symbol"] in self._funding_interval_hours:
                fr[row["symbol"]] = Decimal(row["lastFundingRate"]) * Decimal(
                    self._standardization_duration_hours / self._funding_interval_hours[row["symbol"]]
                )
            else:
                fr[row["symbol"]] = Decimal(row["lastFundingRate"])
        return fr

    async def ws_subscription_payload(self):
        """
        订阅WS Channel of Mark price and funding rate for all symbols
        """
        fundingrate_params = ["!markPrice@arr"]
        payload = {"method": "SUBSCRIBE", "params": fundingrate_params, "id": 101}
        return payload

    def _parse_websocket_message(self, data: Dict) -> Optional[Dict[str, Decimal]]:
        if "result" not in data and len(data) > 0 and "markPriceUpdate" in data[0]["e"]:
            return {str(row["s"]): Decimal(row["r"]) for row in data}
