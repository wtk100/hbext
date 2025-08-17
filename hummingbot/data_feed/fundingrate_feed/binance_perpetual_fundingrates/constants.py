from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

REST_URL = "https://fapi.binance.com"
HEALTH_CHECK_ENDPOINT = "/fapi/v1/ping"
MARK_PRICE_URL = "/fapi/v1/premiumIndex"
FUNDING_INFO_URL = "/fapi/v1/fundingInfo"
WSS_URL = "wss://fstream.binance.com/ws"

REQUEST_WEIGHT = "REQUEST_WEIGHT"

RATE_LIMITS = [
    # could be 2400
    RateLimit(REQUEST_WEIGHT, limit=1200, time_interval=60),
    # could be 2400
    RateLimit(MARK_PRICE_URL, weight=1, limit=1200, time_interval=60, linked_limits=[LinkedLimitWeightPair("raw", 1)]),
    RateLimit(FUNDING_INFO_URL, weight=1, limit=500, time_interval=300),
    # could be 2400
    RateLimit(HEALTH_CHECK_ENDPOINT, limit=1200, time_interval=60, linked_limits=[LinkedLimitWeightPair("raw", 1)])]
