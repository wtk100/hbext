#########################################################################################################################################
# 此类是负责与交易所互动，跟踪维护Order Book信息的类，包括三部分信息：最新交易信息、订单簿增量更新、订单簿快照.
# 1. 获取WS连接并监听OrderBook消息：trade/order_book_diff/order_book_snapshot.
# 2. 通过Rest API获取部分信息如最新交易价格、订单簿快照(当WS更新超时).
# 3. 解析WS消息并存入对应队列.
# 注：与self._trading_pairs相关交易所互动有：
#   _init_order_books: 即为了跟踪一个币对的order book而进行的初始化. self._trading_pairs若为空需测试若变动需处理(注意_order_books，
#   _tracking_message_queues的成员管理，特别注意_tracking_tasks中的任务该取消要取消).
#   同时，当self._trading_pairs变动时，应先处理OrderBookTrackerDataSource.
#########################################################################################################################################
import asyncio
import logging
import time
from collections import defaultdict, deque
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

import pandas as pd

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.event.events import OrderBookTradeEvent
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.logger import HummingbotLogger


class OrderBookTrackerDataSourceType(Enum):
    REMOTE_API = 2
    EXCHANGE_API = 3


class OrderBookTracker:
    PAST_DIFF_WINDOW_SIZE: int = 32
    _obt_logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._obt_logger is None:
            cls._obt_logger = logging.getLogger(__name__)
        return cls._obt_logger

    def __init__(self, data_source: OrderBookTrackerDataSource, trading_pairs: List[str], domain: Optional[str] = None):
        self._domain: Optional[str] = domain
        self._data_source: OrderBookTrackerDataSource = data_source
        self._trading_pairs: List[str] = trading_pairs
        # 用于异步标记所有订单簿是否初始化完成，并用于外部(交易所)检查ready状态
        self._order_books_initialized: asyncio.Event = asyncio.Event()
        # 用_track_single_book方法从币对消息队列_tracking_message_queues/_saved_message_queues中
        # 获取单个币对的消息并更新其订单簿的Tasks，一个币对一个
        self._tracking_tasks: Dict[str, asyncio.Task] = {}
        # 币对订单簿，一个币对一个
        self._order_books: Dict[str, OrderBook] = {}
        # 用于存放每个币对的diff/snapshot消息，由_order_book_diff_router/_order_book_snapshot_router方法存放，
        # 由_track_single_book取出并处理到订单簿中，一个币对一个
        self._tracking_message_queues: Dict[str, asyncio.Queue] = {}
        # _track_single_book一边处理diff消息一边放进币对对应的此队列中，用于后续获取到snapshot后将比其更新的diff
        # 消息应用到snapshot上，一个币对一个
        self._past_diffs_windows: Dict[str, Deque] = defaultdict(lambda: deque(maxlen=self.PAST_DIFF_WINDOW_SIZE))
        # 用于存放所有incoming的diff消息，由data_source存放，由_order_book_diff_router取出并放到
        # _tracking_message_queues中每个币对对应的消息队列中
        self._order_book_diff_stream: asyncio.Queue = asyncio.Queue()
        # 用于存放所有incoming的snapshot消息，由data_source存放，由_order_book_snapshot_router取出并放到
        # _tracking_message_queues中每个币对对应的消息队列中
        self._order_book_snapshot_stream: asyncio.Queue = asyncio.Queue()
        # 用于存放所有incoming的trade消息，由data_source存放，由_emit_trade_event_loop取出并处理到订单簿中
        self._order_book_trade_stream: asyncio.Queue = asyncio.Queue()
        self._ev_loop: asyncio.BaseEventLoop = asyncio.get_event_loop()
        # 当初始化未完成时，若已经开始收到diff消息，_order_book_diff_router先将消息存放到此队列，
        # 待初始化完成后，由_track_single_book取出并处理到订单簿中，一个币对一个
        self._saved_message_queues: Dict[str, Deque[OrderBookMessage]] = defaultdict(lambda: deque(maxlen=1000))

        # 以下均为start方法中，异步调用对应方法的Tasks，用于stop时cancel
        self._emit_trade_event_task: Optional[asyncio.Task] = None
        self._init_order_books_task: Optional[asyncio.Task] = None
        self._order_book_diff_listener_task: Optional[asyncio.Task] = None
        self._order_book_trade_listener_task: Optional[asyncio.Task] = None
        self._order_book_snapshot_listener_task: Optional[asyncio.Task] = None
        self._order_book_diff_router_task: Optional[asyncio.Task] = None
        self._order_book_snapshot_router_task: Optional[asyncio.Task] = None
        self._update_last_trade_prices_task: Optional[asyncio.Task] = None
        self._order_book_stream_listener_task: Optional[asyncio.Task] = None

    @property
    def data_source(self) -> OrderBookTrackerDataSource:
        return self._data_source

    @property
    def order_books(self) -> Dict[str, OrderBook]:
        return self._order_books

    @property
    def ready(self) -> bool:
        return self._order_books_initialized.is_set()

    @property
    def snapshot(self) -> Dict[str, Tuple[pd.DataFrame, pd.DataFrame]]:
        return {
            trading_pair: order_book.snapshot
            for trading_pair, order_book in self._order_books.items()
        }

    def start(self):
        self.stop()
        self._init_order_books_task = safe_ensure_future(
            # 1. 用data_source调API初始化订单簿并放进self._order_books.
            # 2. 初始化每个币对的MQ并放进self._tracking_message_queues.
            # 3. 启动跟踪每个币对diff/snapshot消息并处理到订单簿中的循环任务并把任务(调_track_single_book)放进self._tracking_tasks.
            self._init_order_books()
        )
        self._emit_trade_event_task = safe_ensure_future(
            # 启动从_order_book_trade_stream取出所有incoming的trade消息并处理到订单簿中的循环任务
            self._emit_trade_event_loop()
        )
        # 以下4个call启动data_source的4个listen循环任务方法:
        # listen_for_subscriptions: 订阅WS消息，判断WS消息类别并分别放到data_source的4个消息队列中(snapshot, diff, trade, fundinginfo)
        # listen_for_order_book_diffs: 从data_source的diff消息队列取出消息、解析、放到此类的_order_book_diff_stream队列中
        # listen_for_order_book_snapshots: 从data_source的snapshot消息队列取出消息、解析、放到此类的_order_book_snapshot_stream队列中
        # listen_for_trades: 从data_source的trade消息队列取出消息、解析、放到此类的_order_book_trade_stream队列中
        # 注意：相比OrderBookTrackerDataSource，PerpetualAPIOrderBookDataSource及其子类新增了listen_for_funding_info方法，
        #      但此类并未调用listen_for_funding_info，而是由PerpetualDerivativePyBase调用, stream队列在其成员PerpetualTrading类中.
        self._order_book_diff_listener_task = safe_ensure_future(
            self._data_source.listen_for_order_book_diffs(self._ev_loop, self._order_book_diff_stream)
        )
        self._order_book_trade_listener_task = safe_ensure_future(
            self._data_source.listen_for_trades(self._ev_loop, self._order_book_trade_stream)
        )
        self._order_book_snapshot_listener_task = safe_ensure_future(
            self._data_source.listen_for_order_book_snapshots(self._ev_loop, self._order_book_snapshot_stream)
        )
        self._order_book_stream_listener_task = safe_ensure_future(
            self._data_source.listen_for_subscriptions()
        )
        self._order_book_diff_router_task = safe_ensure_future(
            # 启动从_order_book_diff_stream队列获取diff消息并分币对放到_tracking_message_queues/_saved_message_queues的循环任务
            self._order_book_diff_router()
        )
        self._order_book_snapshot_router_task = safe_ensure_future(
            # 启动从_order_book_snapshot_stream队列获取snapshot消息并分币对放到_tracking_message_queues的循环任务
            self._order_book_snapshot_router()
        )
        self._update_last_trade_prices_task = safe_ensure_future(
            # 启动在初始化完成后, 持续检查, 如果WS更新trade不及时, 就通过交易所类用API获取最新trade并处理到订单簿中的循环任务
            self._update_last_trade_prices_loop()
        )

    def stop(self):
        if self._init_order_books_task is not None:
            self._init_order_books_task.cancel()
            self._init_order_books_task = None
        if self._emit_trade_event_task is not None:
            self._emit_trade_event_task.cancel()
            self._emit_trade_event_task = None
        if self._order_book_diff_listener_task is not None:
            self._order_book_diff_listener_task.cancel()
            self._order_book_diff_listener_task = None
        if self._order_book_snapshot_listener_task is not None:
            self._order_book_snapshot_listener_task.cancel()
            self._order_book_snapshot_listener_task = None
        if self._order_book_trade_listener_task is not None:
            self._order_book_trade_listener_task.cancel()
            self._order_book_trade_listener_task = None

        if self._order_book_diff_router_task is not None:
            self._order_book_diff_router_task.cancel()
            self._order_book_diff_router_task = None
        if self._order_book_snapshot_router_task is not None:
            self._order_book_snapshot_router_task.cancel()
            self._order_book_snapshot_router_task = None
        if self._update_last_trade_prices_task is not None:
            self._update_last_trade_prices_task.cancel()
            self._update_last_trade_prices_task = None
        if self._order_book_stream_listener_task is not None:
            self._order_book_stream_listener_task.cancel()
        if len(self._tracking_tasks) > 0:
            for _, task in self._tracking_tasks.items():
                task.cancel()
            self._tracking_tasks.clear()
        self._order_books_initialized.clear()

    async def wait_ready(self):
        await self._order_books_initialized.wait()

    async def _update_last_trade_prices_loop(self):
        '''
        Updates last trade price for all order books through REST API, it is to initiate last_trade_price and as
        fall-back mechanism for when the web socket update channel fails.
        由start开启: Order book初始化完成后, 直接开始循环检查, 如果WS更新trade不及时, 就通过交易所类用API获取有order book的币对的最新
        交易价格并更新到其对应的order book对象中.
        '''
        await self._order_books_initialized.wait()
        while True:
            try:
                outdateds = [t_pair for t_pair, o_book in self._order_books.items()
                             if o_book.last_applied_trade < time.perf_counter() - (60. * 3)
                             and o_book.last_trade_price_rest_updated < time.perf_counter() - 5]
                if outdateds:
                    args = {"trading_pairs": outdateds}
                    if self._domain is not None:
                        args["domain"] = self._domain
                    last_prices = await self._data_source.get_last_traded_prices(**args)
                    for trading_pair, last_price in last_prices.items():
                        self._order_books[trading_pair].last_trade_price = last_price
                        self._order_books[trading_pair].last_trade_price_rest_updated = time.perf_counter()
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network("Unexpected error while fetching last trade price.", exc_info=True)
                await asyncio.sleep(30)

    # 通过OrderBookTrackerDataSource初始化一个币对的order book.
    async def _initial_order_book_for_trading_pair(self, trading_pair: str) -> OrderBook:
        return await self._data_source.get_new_order_book(trading_pair)

    async def _init_order_books(self):
        """
        Initialize order books
        由start开启: 初始化self._trading_pairs所有币对的order book. 这里包括为每个币对：
        1. 初始化order book并放进self._order_books.
        2. 初始化MQ并放进self._tracking_message_queues.
        3. 开始跟踪order book并把跟踪任务放进self._tracking_tasks.
        最后set self._order_books_initialized事件.
        """
        for index, trading_pair in enumerate(self._trading_pairs):
            self._order_books[trading_pair] = await self._initial_order_book_for_trading_pair(trading_pair)
            self._tracking_message_queues[trading_pair] = asyncio.Queue()
            self._tracking_tasks[trading_pair] = safe_ensure_future(self._track_single_book(trading_pair))
            self.logger().info(f"Initialized order book for {trading_pair}. "
                               f"{index + 1}/{len(self._trading_pairs)} completed.")
            await self._sleep(delay=1)
        self._order_books_initialized.set()

    async def _order_book_diff_router(self):
        """
        Routes the real-time order book diff messages to the correct order book.
        从order book diff stream获取消息并 转存 进每个币对对应的MQ中. 
        注: 不等_init_order_books初始化完成, 未初始化完成的币对的diff消息会暂存至self._saved_message_queues.
        """
        last_message_timestamp: float = time.time()
        messages_queued: int = 0
        messages_accepted: int = 0
        messages_rejected: int = 0

        while True:
            try:
                # 在listen_for_order_book_diffs方法中指定由OrderBookTrackerDataSource把WS消息放进_order_book_diff_stream
                ob_message: OrderBookMessage = await self._order_book_diff_stream.get()
                trading_pair: str = ob_message.trading_pair

                # self._tracking_message_queues中还没有币对，那么_init_order_books的初始化还没完成，此时先把diff消息存
                # 到self._saved_message_queues并continue循环
                if trading_pair not in self._tracking_message_queues:
                    messages_queued += 1
                    # Save diff messages received before snapshots are ready
                    self._saved_message_queues[trading_pair].append(ob_message)
                    continue
                
                # self._tracking_message_queues中已有币对，那么_init_order_books的初始化已经完成，此时MQ和Order Book都可以取出
                message_queue: asyncio.Queue = self._tracking_message_queues[trading_pair]
                # Check the order book's initial update ID. If it's larger, don't bother.
                order_book: OrderBook = self._order_books[trading_pair]

                # Order Book的状态比消息更新就忽略消息并continue
                if order_book.snapshot_uid > ob_message.update_id:
                    messages_rejected += 1
                    continue
                # 否则把消息放进MQ
                await message_queue.put(ob_message)
                messages_accepted += 1

                # Log some statistics.
                # 每60秒打印一次counters并重置counters
                now: float = time.time()
                if int(now / 60.0) > int(last_message_timestamp / 60.0):
                    self.logger().debug(f"Diff messages processed: {messages_accepted}, "
                                        f"rejected: {messages_rejected}, queued: {messages_queued}")
                    messages_accepted = 0
                    messages_rejected = 0
                    messages_queued = 0

                last_message_timestamp = now
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unexpected error routing order book messages.",
                    exc_info=True,
                    app_warning_msg="Unexpected error routing order book messages. Retrying after 5 seconds."
                )
                await asyncio.sleep(5.0)

    async def _order_book_snapshot_router(self):
        """
        Route the real-time order book snapshot messages to the correct order book.
        从order book snapshot stream获取消息并 转存 进每个币对对应的MQ中. 
        注: 要等_init_order_books初始化完成, 完成后仍未初始化的币对snapshot消息会忽略.
        """
        await self._order_books_initialized.wait()
        while True:
            try:
                ob_message: OrderBookMessage = await self._order_book_snapshot_stream.get()
                trading_pair: str = ob_message.trading_pair
                if trading_pair not in self._tracking_message_queues:
                    continue
                message_queue: asyncio.Queue = self._tracking_message_queues[trading_pair]
                await message_queue.put(ob_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unknown error. Retrying after 5 seconds.", exc_info=True)
                await asyncio.sleep(5.0)

    async def _track_single_book(self, trading_pair: str):
        past_diffs_window = self._past_diffs_windows[trading_pair]

        message_queue: asyncio.Queue = self._tracking_message_queues[trading_pair]
        order_book: OrderBook = self._order_books[trading_pair]
        last_message_timestamp: float = time.time()
        diff_messages_accepted: int = 0

        while True:
            try:
                saved_messages: Deque[OrderBookMessage] = self._saved_message_queues[trading_pair]

                # Process saved messages first if there are any
                # 如果有order book初始化完成之前就存下来的消息，先处理
                if len(saved_messages) > 0:
                    message = saved_messages.popleft()
                else:
                    message = await message_queue.get()

                # 对于diff消息，一边处理一边存下来放在past_diffs_window中，以备在收到的snapshot上使用
                if message.type is OrderBookMessageType.DIFF:
                    order_book.apply_diffs(message.bids, message.asks, message.update_id)
                    past_diffs_window.append(message)
                    diff_messages_accepted += 1

                    # Output some statistics periodically.
                    now: float = time.time()
                    if int(now / 60.0) > int(last_message_timestamp / 60.0):
                        self.logger().debug(f"Processed {diff_messages_accepted} order book diffs for {trading_pair}.")
                        diff_messages_accepted = 0
                    last_message_timestamp = now
                # 对于snapshot消息，用snapshot重置后，还需用应用所有更新的diff消息，从而把order book恢复到最新状态
                elif message.type is OrderBookMessageType.SNAPSHOT:
                    past_diffs: List[OrderBookMessage] = list(past_diffs_window)
                    order_book.restore_from_snapshot_and_diffs(message, past_diffs)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    f"Unexpected error tracking order book for {trading_pair}.",
                    exc_info=True,
                    app_warning_msg="Unexpected error tracking order book. Retrying after 5 seconds."
                )
                await asyncio.sleep(5.0)

    async def _emit_trade_event_loop(self):
        last_message_timestamp: float = time.time()
        messages_accepted: int = 0
        messages_rejected: int = 0
        await self._order_books_initialized.wait()
        while True:
            try:
                trade_message: OrderBookMessage = await self._order_book_trade_stream.get()
                trading_pair: str = trade_message.trading_pair

                if trading_pair not in self._order_books:
                    messages_rejected += 1
                    continue

                order_book: OrderBook = self._order_books[trading_pair]
                order_book.apply_trade(OrderBookTradeEvent(
                    trading_pair=trade_message.trading_pair,
                    timestamp=trade_message.timestamp,
                    price=float(trade_message.content["price"]),
                    amount=float(trade_message.content["amount"]),
                    trade_id=trade_message.trade_id,
                    type=TradeType.SELL if
                    trade_message.content["trade_type"] == float(TradeType.SELL.value) else TradeType.BUY
                ))

                messages_accepted += 1

                # Log some statistics.
                now: float = time.time()
                if int(now / 60.0) > int(last_message_timestamp / 60.0):
                    self.logger().debug(f"Trade messages processed: {messages_accepted}, rejected: {messages_rejected}")
                    messages_accepted = 0
                    messages_rejected = 0

                last_message_timestamp = now
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unexpected error routing order book messages.",
                    exc_info=True,
                    app_warning_msg="Unexpected error routing order book messages. Retrying after 5 seconds."
                )
                await asyncio.sleep(5.0)

    @staticmethod
    async def _sleep(delay: float):
        await asyncio.sleep(delay=delay)
