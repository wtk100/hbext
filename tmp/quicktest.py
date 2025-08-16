import asyncio
import threading
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Dict, List
import pandas as pd
from IPython.display import clear_output
from hummingbot.client.config.config_crypt import BaseSecretsManager, ETHKeyFileSecretManger
from hummingbot.client.config.config_helpers import (
    ClientConfigAdapter,
    all_configs_complete,
    create_yml_files_legacy,
    load_client_config_map_from_file,
    load_strategy_config_map_from_file,
    read_system_configs_from_yml,
)
from hummingbot.client.config.security import Security
from hummingbot.client.hummingbot_application import HummingbotApplication
from hummingbot.client.settings import STRATEGIES_CONF_DIR_PATH, AllConnectorSettings, required_exchanges
from hummingbot.client.command.gateway_command import GatewayCommand
from hummingbot.user.user_balances import UserBalances

async def hb_app():
    secrets_manager_cls = ETHKeyFileSecretManger
    secrets_manager = secrets_manager_cls('qoakzm,12345')
    client_config_map = load_client_config_map_from_file()

    if not Security.login(secrets_manager):
        print("Invalid password.")
    else:
        print("login succeed.")
    await Security.wait_til_decryption_done()
    AllConnectorSettings.initialize_paper_trade_settings(client_config_map.paper_trade.paper_trade_exchanges)
    hb = HummingbotApplication.main_application(client_config_map=client_config_map)
    if not Security.is_decryption_done():
        print('  - Security check: Encrypted files are being processed. Please wait and try again later.')
    else:
        print("decryption done.")

    connections = await UserBalances.instance().update_exchanges(client_config_map, exchanges=required_exchanges)    
    invalid_conns = {}
    invalid_conns.update({ex: err_msg for ex, err_msg in connections.items() if ex in required_exchanges and err_msg is not None})
    if invalid_conns:
        print('  - Exchange check: Invalid connections:')
        for ex, err_msg in invalid_conns.items():
            print(f"    {ex}: {err_msg}")
    else:
        print('Exchange connection check: All connections confirmed.')
    return hb


def exchange_readiness_check(hb:HummingbotApplication):
    hb.start(script="log_price_example.py")

async def exec_tests():
    hb = await hb_app()
    exchange_readiness_check(hb)

asyncio.run(exec_tests())