################################################################################################################
# 注：okx的WS订阅超30秒无消息会自动关闭链接.
################################################################################################################
import logging
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.connector.derivative.okx_perpetual.okx_perpetual_derivative import OkxPerpetualDerivative
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.data_feed.fundingrate_feed.fundingrate_base import FundingRateBase
from hummingbot.data_feed.fundingrate_feed.okx_perpetual_fundingrates import constants as CONSTANTS
from hummingbot.logger import HummingbotLogger


class OkxPerpetualFundingRates(FundingRateBase):
    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self,
                 exchange: OkxPerpetualDerivative,
                 trading_pairs: Optional[List[str]],
                 update_interval: float = 10.0,
                 standardization_duration_hours: int = 24):
        super().__init__(exchange, trading_pairs, update_interval, standardization_duration_hours)

    @property
    def name(self):
        return "okx_perpetual_fundingrates"

    @property
    def health_check_url(self):
        return self.rest_url + CONSTANTS.HEALTH_CHECK_ENDPOINT

    @property
    def rest_url(self):
        return CONSTANTS.REST_URL

    @property
    def fundingrate_endpoint(self):
        return CONSTANTS.FUNDING_RATE_URL

    @property
    def fundingrate_url(self):
        return self.rest_url + CONSTANTS.FUNDING_RATE_URL

    @property
    def wss_url(self):
        return CONSTANTS.WSS_URL

    @property
    def rate_limits(self):
        return CONSTANTS.RATE_LIMITS

    async def check_network(self) -> NetworkStatus:
        rest_assistant = await self._api_factory.get_rest_assistant()
        await rest_assistant.execute_request(url=self.health_check_url,
                                             throttler_limit_id=CONSTANTS.HEALTH_CHECK_ENDPOINT)
        return NetworkStatus.CONNECTED

    def _get_rest_fundingrate_params(self) -> Optional[dict]:
        """
        为减少rest api request数量, symbol传ANY, 直接全部获取
        For API documentation, please refer to:
        https://developers.okx.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price
        """
        params = {
            "instId": "ANY",
        }
        return params

    def _parse_rest_fundingrates(self, data: Dict) -> Dict[str, Decimal]:
        return {
            str(row["instId"]):
            Decimal(row["fundingRate"]) *
            Decimal(self._standardization_duration_hours * 60 * 60 /
                    (int(float(row["nextFundingTime"]) * 1e-3) - int(float(row["fundingTime"]) * 1e-3)))
            for row in data["data"]
        }

    async def ws_subscription_payload(self):
        """
        订阅WS Channel of funding rate for all self._trading_pairs symbols
        """
        ex_trading_pairs = [
            await self.get_exchange_trading_pair(trading_pair=trading_pair)
            for trading_pair in self._trading_pairs
        ]
        funding_rates_args = [
            {
                "channel": CONSTANTS.FUNDING_RATE_CHANNEL,
                "instId": ex_trading_pair
            } for ex_trading_pair in ex_trading_pairs
        ]
        funding_rates_payload = {
            "id": "101",
            "op": "subscribe",
            "args": funding_rates_args,
        }
        return funding_rates_payload

    def _parse_websocket_message(self, data: Dict) -> Optional[Dict[str, Decimal]]:
        if "event" not in data and "funding-rate" in data["arg"]["channel"]:
            data = data["data"]
            return {
                str(row["instId"]):
                Decimal(row["fundingRate"]) *
                Decimal(self._standardization_duration_hours * 60 * 60 /
                        (int(float(row["nextFundingTime"]) * 1e-3) - int(float(row["fundingTime"]) * 1e-3)))
                for row in data
            }
