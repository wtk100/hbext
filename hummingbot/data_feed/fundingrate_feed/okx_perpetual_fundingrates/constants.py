from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit

REST_URL = "https://www.okx.com"
HEALTH_CHECK_ENDPOINT = "/api/v5/public/time"
FUNDING_RATE_URL = "/api/v5/public/funding-rate"
WSS_URL = "wss://ws.okx.com:8443/ws/v5/public"
FUNDING_RATE_CHANNEL = "funding-rate"

# Rate Limits of HEALTH_CHECK_ENDPOINT
# Get system time (https://www.okx.com/docs-v5/en/#public-data-rest-api-get-system-time)
# Retrieve API server time.
# Rate Limit: 10 requests per 2 seconds
# Rate limit rule: IP
# # Rate Limits of FUNDING_RATE_URL
# Get system time (https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate)
# Retrieve API server time.
# Rate Limit: 10 requests per 2 seconds
# Rate limit rule: IP + Instrument ID (could be ANY)
RATE_LIMITS = [
    RateLimit(FUNDING_RATE_URL, limit=10, time_interval=2, linked_limits=[LinkedLimitWeightPair("raw", 1)]),
    RateLimit(HEALTH_CHECK_ENDPOINT, limit=10, time_interval=2, linked_limits=[LinkedLimitWeightPair("raw", 1)])]
