from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class LogPricesExample(ScriptStrategyBase):
    """
    This example shows how to get the ask and bid of a market and log it to the console.
    """
    markets = {
        "binance": {"BTC-USDT", },
    }

    def on_tick(self):
        for connector_name, connector in self.connectors.items():
            self.logger().info(f"{connector_name} ticked. BTC: {connector.get_mid_price('BTC-USDT')}")
