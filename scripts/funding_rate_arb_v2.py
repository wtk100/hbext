"""
XX
"""
from typing import Dict, List, Optional, Set

from pydantic import BaseModel

from hummingbot.client.hummingbot_application import HummingbotApplication
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class FundingRateArbitrage(ScriptStrategyBase):
    """
    XX
    """
    markets: Dict[str, Set[str]] = {
        "okx_perpetual": {"BTC-USDT", },
    }

    def __init__(self, connectors: Dict[str, ConnectorBase], config: Optional[BaseModel] = None):
        super().__init__(connectors, config)
        self._hb_app = HummingbotApplication.main_application()
        self._trading_core = self._hb_app.trading_core
        self._ticked_seconds = 0

    def _add_exchange(self, ex_name: str, trading_pairs: List[str] = ["BTC-USDT"]):
        exchange = self._trading_core.create_connector(ex_name, trading_pairs)
        self.add_markets(list([exchange]))
        self.connectors[ex_name] = exchange
        FundingRateArbitrage.markets[ex_name] = set(trading_pairs)
        self.ready_to_trade = False

    def _remove_exchange(self, ex_name: str):
        self.remove_markets(list([self.connectors[ex_name]]))
        self._trading_core.remove_connector(ex_name)
        self.connectors.pop(ex_name)
        FundingRateArbitrage.markets.pop(ex_name)

    def _reset_trading_pairs(self, ex_name: str, trading_pairs: List[str] = ["BTC-USDT"]):
        self.remove_markets(list([self.connectors[ex_name]]))
        exchange = self._trading_core.reset_trading_pairs(ex_name, trading_pairs)
        self.add_markets(list([exchange]))
        self.connectors.pop(ex_name)
        FundingRateArbitrage.markets.pop(ex_name)
        self.connectors[ex_name] = exchange
        FundingRateArbitrage.markets[ex_name] = set(trading_pairs)
        self.ready_to_trade = False

    def _add_trading_pairs(self, ex_name: str, trading_pairs: List[str] = ["BTC-USDT"]):
        self.remove_markets(list([self.connectors[ex_name]]))
        exchange = self._trading_core.add_trading_pairs(ex_name, trading_pairs)
        self.add_markets(list([exchange]))
        self.connectors.pop(ex_name)
        FundingRateArbitrage.markets.pop(ex_name)
        self.connectors[ex_name] = exchange
        FundingRateArbitrage.markets[ex_name] = set(trading_pairs)
        self.ready_to_trade = False

    def _activate_market(self, ex_name: str, trading_pairs: List[str] = ["BTC-USDT"]):
        if ex_name in FundingRateArbitrage.markets:
            if FundingRateArbitrage.markets[ex_name] != trading_pairs:
                self._reset_trading_pairs(ex_name, trading_pairs)
        else:
            self._add_exchange(ex_name, trading_pairs)

    def _deactivate_market(self, ex_name: str):
        if ex_name in FundingRateArbitrage.markets:
            self._remove_exchange(ex_name)

    def on_tick(self):
        market_options = [
            ("binance_perpetual", ["BTC-USDT"]),
            ("binance_perpetual", ["XRP-USDT"]),
            ("okx_perpetual", ["XRP-USDT"]),
            ("binance_perpetual", ["LTC-USDT"]),
            ("okx_perpetual", ["SOL-USDT"]),
            ("okx_perpetual", ["ETH-USDT"]),
            ("binance_perpetual", ["SOL-USDT"]),
            ("binance_perpetual", ["ETH-USDT"]),
        ]
        self._ticked_seconds += 1
        if self._ticked_seconds % 70 == 0:
            ex_name, trading_pairs = market_options[self._ticked_seconds // 70 - 1]
            self.logger().info(f"Switching to {ex_name} and {trading_pairs}...")
            self.logger().info(f"Activating {ex_name}...")
            self._activate_market(ex_name, trading_pairs)
            for ex_name_existing in FundingRateArbitrage.markets.keys():
                if ex_name_existing != ex_name:
                    self.logger().info(f"Deactivating {ex_name_existing}...")
                    self._deactivate_market(ex_name_existing)
        if self._ticked_seconds == self._ticked_seconds // 70 * 10 + 5:
            self.logger().info(self._trading_core.connector_manager.get_status())

        for connector_name, connector in self.connectors.items():
            info = f"Connector {connector_name} - traing_pairs: " + \
                ",".join([f"{tp}: {connector.get_mid_price(tp)}" for tp in connector.trading_pairs])
            self.logger().info(info)

    # async def on_stop(self):
    #     pass
