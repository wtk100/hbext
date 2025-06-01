#!/usr/bin/env python

from typing import Callable

from hummingbot.core.event.event_listener import EventListener
from hummingbot.core.pubsub import PubSub


# 负责将一个事件推给一个函数处理，函数参数为任意
class EventForwarder(EventListener):
    def __init__(self, to_function: Callable[[any], None]):
        super().__init__()
        self._to_function: Callable[[any], None] = to_function

    def __call__(self, arg: any):
        self._to_function(arg)


# 负责将一个事件推给一个函数处理，函数参数为：event_tag(int)， event_caller(PubSub，比如Connector)和其他任意参数(比如Event对象)
class SourceInfoEventForwarder(EventListener):
    def __init__(self, to_function: Callable[[int, PubSub, any], None]):
        super().__init__()
        self._to_function: Callable[[int, PubSub, any], None] = to_function

    def __call__(self, arg: any):
        self._to_function(self.current_event_tag, self.current_event_caller, arg)
