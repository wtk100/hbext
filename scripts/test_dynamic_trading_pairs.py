from typing import Dict, List, Optional

from pydantic import BaseModel

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class LogPricesExample(ScriptStrategyBase):
    """
    This example shows how to get the ask and bid of a market and log it to the console.
    """

    markets = {
        "okx": {
            "BTC-USDT",
        },
    }

    def __init__(self, connectors: Dict[str, ConnectorBase], config: Optional[BaseModel] = None):
        super().__init__(connectors, config)
        self._ticks = 0

    def on_tick(self):
        self._ticks += 1

        for connector_name, connector in self.connectors.items():
            self.logger().info(
                f"{connector_name} ticked.| "
                + "| ".join([f"{tp}: {connector.get_mid_price(tp)}" for tp in connector.trading_pairs])
            )
            if self._ticks == 5:
                new_tps: List[str] = ["ETH-USDT", "XRP-USDT", "SOL-USDT"]
                self.logger().info(f"【strategy】updating connector's trading_pairs to {new_tps}.")
                connector.update_trading_pairs(new_tps)
                self.ready_to_trade = False
                self.logger().info(f"【strategy】set connector's trading_pairs to {connector.trading_pairs} done.")
            if self._ticks == 35:
                new_tps: List[str] = ["BTC-USDT", "LTC-USDT"]
                self.logger().info(f"【strategy】updating connector's trading_pairs to {new_tps}.")
                connector.update_trading_pairs(new_tps)
                self.ready_to_trade = False
                self.logger().info(f"【strategy】set connector's trading_pairs to {connector.trading_pairs} done.")
