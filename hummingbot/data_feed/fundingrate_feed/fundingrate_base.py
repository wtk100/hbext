import asyncio
import time
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.connector.exchange_base import ExchangeBase
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.network_base import NetworkBase
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger


class FundingRateBase(NetworkBase):
    _logger: Optional[HummingbotLogger] = None
    """
    This class serves as a base class for fetching and storing funding rate data from a cryptocurrency exchange.
    The class uses the Rest and WS Assistants for all the IO operations, and a dict to store funding rates.
    Also implements the Throttler module for API rate limiting, and it's preferred since the real time data should
    not be necessary via websockets due to low frequency of funding rate update from exchange.
    """

    def __init__(self,
                 exchange: ExchangeBase,
                 trading_pairs: Optional[List[str]],
                 update_interval: float = 10.0,
                 standardization_duration_hours: int = 24):
        super().__init__()
        async_throttler = AsyncThrottler(rate_limits=self.rate_limits)
        self._exchange = exchange
        self._api_factory = WebAssistantsFactory(throttler=async_throttler)
        self._fetch_fundingrate_task: Optional[asyncio.Task] = None
        self._listen_fundingrate_task: Optional[asyncio.Task] = None
        self._trading_pairs = trading_pairs if trading_pairs is not None and len(trading_pairs) > 0 else exchange.all_trading_pairs()
        self._funding_rates: Dict[str, Decimal] = {}
        self._rest_update_interval: float = update_interval
        self._standardization_duration_hours: float = standardization_duration_hours
        self._last_update_time: Optional[datetime] = None
        self._ping_timeout = None

    async def initialize_exchange_data(self):
        """
        This method is used to set up the exchange data before starting the network.

        (I.E. get the trading pair quanto multiplier, special trading pair or symbol notation, etc.)
        """
        pass

    async def start_network(self):
        """
        This method starts the network and starts a task for listen_for_subscriptions.
        """
        await self.stop_network()
        await self.initialize_exchange_data()
        self._fetch_fundingrate_task = safe_ensure_future(self.fetch_fundingrates_loop())
        # self._listen_fundingrate_task = safe_ensure_future(self.listen_for_subscriptions())

    async def stop_network(self):
        """
        This method stops the network by canceling the _listen_fundingrate_task task.
        """
        if self._fetch_fundingrate_task is not None:
            self._fetch_fundingrate_task.cancel()
            self._fetch_fundingrate_task = None
        if self._listen_fundingrate_task is not None:
            self._listen_fundingrate_task.cancel()
            self._listen_fundingrate_task = None

    @property
    def ready(self):
        """
        This property returns a boolean indicating whether all trading pairs got funding rate data initialized from WS.
        """
        return len(self._trading_pairs) <= len(self._funding_rates.values())

    @property
    def funding_rates(self):
        return self._funding_rates

    @property
    def last_update_time(self):
        return self._last_update_time

    @property
    def name(self):
        raise NotImplementedError

    @property
    def health_check_url(self):
        raise NotImplementedError

    @property
    def rest_url(self):
        raise NotImplementedError

    @property
    def fundingrate_endpoint(self):
        raise NotImplementedError

    @property
    def fundingrate_url(self):
        raise NotImplementedError

    @property
    def wss_url(self):
        raise NotImplementedError

    @property
    def rate_limits(self):
        raise NotImplementedError

    async def check_network(self) -> NetworkStatus:
        raise NotImplementedError

    async def get_exchange_trading_pair(self, trading_pair: str) -> str:
        return await self._exchange.exchange_symbol_associated_to_pair(trading_pair)

    async def get_hb_trading_pair(self, ex_trading_pair: str) -> str:
        return await self._exchange.trading_pair_associated_to_exchange_symbol(ex_trading_pair)

    def _reset_fundingrate(self):
        self._funding_rates.clear()

    @property
    def _rest_method(self) -> RESTMethod:
        return RESTMethod.GET

    @property
    def _rest_throttler_limit_id(self):
        return self.fundingrate_endpoint

    async def fetch_fundingrates_loop(self):
        while True:
            try:
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

    async def fetch_fundingrates(self):
        params = self._get_rest_fundingrate_params()
        headers = self._get_rest_fundingrate_headers()
        kwargs = {}
        rest_assistant = await self._api_factory.get_rest_assistant()
        fundingrates = await rest_assistant.execute_request(url=self.fundingrate_url,
                                                            throttler_limit_id=self._rest_throttler_limit_id,
                                                            params=params,
                                                            data=self._rest_payload(**kwargs),
                                                            headers=headers,
                                                            method=self._rest_method)
        funding_info_updates = self._parse_rest_fundingrates(fundingrates)
        await self._update_all_funding_info(funding_info_updates)

    def _get_rest_fundingrate_params(self) -> Optional[dict]:
        """
        This method returns the parameters for the funding rate REST request.
        """
        return None

    def _get_rest_fundingrate_headers(self):
        """
        This method returns the headers for the funding rate REST request.
        """
        pass

    def _rest_payload(self, **kwargs) -> Optional[dict]:
        return None

    def _parse_rest_fundingrates(self, data: Dict) -> Dict[str, Decimal]:
        """
        This method parses the funding rate data fetched from the REST API.

        :param data: the funding rate data fetched from the REST API
        """
        raise NotImplementedError

    async def listen_for_subscriptions(self):
        """
        Connects to the funding rate websocket endpoint and listens to the messages sent by the exchange.
        """
        ws: Optional[WSAssistant] = None
        while True:
            try:
                ws: WSAssistant = await self._connected_websocket_assistant()
                await self._subscribe_channels(ws)
                await self._process_websocket_messages(websocket_assistant=ws)
            except asyncio.CancelledError:
                raise
            except ConnectionError as connection_exception:
                self.logger().warning(f"The websocket connection was closed ({connection_exception})")
            except Exception:
                self.logger().exception(
                    "Unexpected error occurred when listening to public funding rates. Retrying in 1 seconds...",
                )
                await self._sleep(1.0)
            finally:
                await self._on_interruption(websocket_assistant=ws)

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        await ws.connect(ws_url=self.wss_url, ping_timeout=self._ping_timeout)
        return ws

    async def ws_subscription_payload(self):
        """
        This method returns the subscription payload for the websocket connection.
        """
        raise NotImplementedError

    async def _subscribe_channels(self, ws: WSAssistant):
        """
        Subscribes to the funding rate events through the provided websocket connection.
        :param ws: the websocket assistant used to connect to the exchange
        """
        try:
            payload = await self.ws_subscription_payload()
            subscribe_fundingrate_request: WSJSONRequest = WSJSONRequest(payload=payload)
            await ws.send(subscribe_fundingrate_request)
            self.logger().info("Subscribed to public funding rates...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error occurred subscribing to public funding rates...",
                exc_info=True
            )
            raise

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
        while True:
            try:
                await asyncio.wait_for(self._process_websocket_messages_task(websocket_assistant=websocket_assistant),
                                       timeout=self._ping_timeout)
            except asyncio.TimeoutError:
                if self._ping_timeout is not None:
                    ping_request = WSJSONRequest(payload=self._ping_payload)
                    await websocket_assistant.send(request=ping_request)

    async def _process_websocket_messages_task(self, websocket_assistant: WSAssistant):
        # TODO: Isolate ping pong logic
        async for ws_response in websocket_assistant.iter_messages():
            data = ws_response.data
            parsed_message = self._parse_websocket_message(data)
            # parsed messages may be ping or pong messages
            if parsed_message and isinstance(parsed_message, WSJSONRequest):
                await websocket_assistant.send(request=parsed_message)
            elif parsed_message and isinstance(parsed_message, Dict):
                await self._update_all_funding_info(parsed_message)

    def _parse_websocket_message(self, data: Dict) -> Optional[Dict[str, Decimal]]:
        """
        This method must be implemented by a subclass to parse the websocket message into a Dict of [str, Decimal]
        where str is exchange trading pair.

        :param data: the websocket message data
        :return: Optional[Dict[str, Decimal]] object
        """
        raise NotImplementedError

    async def _update_all_funding_info(self, funding_info_updates: Dict[str, Decimal]):
        for tp in self._trading_pairs:
            ex_trading_pair = await self.get_exchange_trading_pair(tp)
            if ex_trading_pair is not None and ex_trading_pair in funding_info_updates.keys():
                self._last_update_time = datetime.now()
                self._funding_rates[tp] = funding_info_updates[ex_trading_pair]

    @property
    def _ping_payload(self):
        return None

    @staticmethod
    async def _sleep(delay):
        """
        Function added only to facilitate patching the sleep in unit tests without affecting the asyncio module
        """
        await asyncio.sleep(delay)

    async def _on_interruption(self, websocket_assistant: Optional[WSAssistant] = None):
        websocket_assistant and await websocket_assistant.disconnect()
        self._funding_rates.clear()

    @staticmethod
    def _time():
        return time.time()
