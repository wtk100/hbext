# Base asset 是交易对中第一个列出的资产，通常表示被购买或出售的资产。例如，在交易对 "BTC/USDT" 中，BTC 是 base asset
# Quote asset 是交易对中第二个列出的资产，用于表示 base asset 的价格。例如，在 "BTC/USDT" 中，USDT 是 quote asset，表示每单位 BTC 的价格
cdef class InFlightOrderBase:
    cdef:
        public str client_order_id
        public str exchange_order_id
        public str trading_pair
        public object order_type
        public object trade_type
        public object price
        public object amount
        public object executed_amount_base
        public object executed_amount_quote
        public str fee_asset
        public object fee_paid
        public str last_state
        public object exchange_order_id_update_event
        public object completely_filled_event
        public double _creation_timestamp
