import asyncio
from collections import deque

from async_timeout import timeout
from typing import (
    List,
    Optional,
)

from hummingbot.core.event.event_listener cimport EventListener
from hummingbot.core.event.events import OrderFilledEvent

cdef class EventLogger(EventListener):
    def __init__(self, event_source: Optional[str] = None):
        super().__init__()
        self._event_source = event_source
        # We limit the amount of events we keep reference to the most recent ones
        # deque：双端队列
        self._generic_logged_events = deque(maxlen=50)
        # But we keep all references to order fill events, because they are required for PnL calculation
        self._generic_logged_events = deque(maxlen=50)
        self._order_filled_logged_events = deque()
        # All keeping events, 初始化一组key-value: OrderFilledEvent类作为key、其初始空队列作为value
        self._logged_events = {OrderFilledEvent: self._order_filled_logged_events}
        self._waiting = {}
        self._wait_returns = {}

    # 返回所有keeping events的List
    @property
    def event_log(self) -> List[any]:
        return list(self._generic_logged_events) + list(self._order_filled_logged_events)

    @property
    def event_source(self) -> str:
        return self._event_source

    # 清空generic和order_filled两个队列
    def clear(self):
        self._generic_logged_events.clear()
        self._order_filled_logged_events.clear()

    async def wait_for(self, event_type, timeout_seconds: float = 180):
        # param event_type：来自events.py中的event定义类
        notifier = asyncio.Event()
        # 在_waiting字典添加：key为新建的事件notifier、value为event_type的元素
        self._waiting[notifier] = event_type

        async with timeout(timeout_seconds):
            # 异步等待新建的事件发生
            await notifier.wait()

        # 从_wait_returns中获取对应事件对象(若超时前事件发生了；来自c_call函数的参数)
        retval = self._wait_returns.get(notifier)
        # 若_wait_returns中有对应事件对象则删除
        if notifier in self._wait_returns:
            del self._wait_returns[notifier]
        # 从_waiting字典中删除key为新建的事件notifier的元素
        del self._waiting[notifier]
        return retval

    def __call__(self, event_object):
        self.c_call(event_object)

    cdef c_call(self, object event_object):
        # 往_logged_events中事件对象的类型对应的队列添加事件对象，若对应队列不存在则添加到_generic_logged_events队列
        self._logged_events.get(type(event_object), self._generic_logged_events).append(event_object)
        # 通知_waiting里所有value为event_object的event_type的事件notifier此事件的发生，并记录事件对象到_wait_returns
        event_object_type = type(event_object)

        should_notify = []
        for notifier, waiting_event_type in self._waiting.items():
            if event_object_type is waiting_event_type:
                should_notify.append(notifier)
                self._wait_returns[notifier] = event_object
        for notifier in should_notify:
            notifier.set()
