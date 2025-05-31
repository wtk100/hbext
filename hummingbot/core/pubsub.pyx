### 处理Event的发布与订阅，包括添加、删除、触发evnt_tag对应的EventListener集合
### 事件是一个程序执行流的驱动来源，驱动EventListener集合执行任务；时间驱动是程序执行流的另一个驱动来源，驱动定时执行任务(由Clock管理)

# distutils: language=c++
# distutils: sources=hummingbot/core/cpp/PyRef.cpp

from cpython cimport(
    PyObject,
    PyWeakref_NewRef,
    PyWeakref_GetObject
)
from cython.operator cimport(
    postincrement as inc,
    dereference as deref,
    address
)
from libcpp.vector cimport vector
from enum import Enum
import logging
import random
from typing import List

from hummingbot.logger import HummingbotLogger
from hummingbot.core.event.event_listener import EventListener
from hummingbot.core.event.event_listener cimport EventListener

class_logger = None


cdef class PubSub:
    """
    PubSub with weak references. This avoids the lapsed listener problem by periodically performing GC on dead
    event listener.

    Dead listener is done by calling c_remove_dead_listeners(), which checks whether the listener weak references are
    alive or not, and removes the dead ones. Each call to c_remove_dead_listeners() takes O(n).

    Here's how the dead listener GC is performed:

    1. c_add_listener():
       Randomly with ADD_LISTENER_GC_PROBABILITY. This assumes c_add_listener() is called frequently and so it doesn't
       make sense to do the GC every time.
    2. c_remove_listener():
       Every time. This assumes c_remove_listener() is called infrequently.
    3. c_get_listeners() and c_trigger_event():
       Every time. Both functions take O(n) already.
    """

    ADD_LISTENER_GC_PROBABILITY = 0.005

    @classmethod
    def logger(cls) -> HummingbotLogger:
        global class_logger
        if class_logger is None:
            class_logger = logging.getLogger(__name__)
        return class_logger

    def __init__(self):
        # _events按event_tag存放对应的事件集合
        self._events = Events()

    def add_listener(self, event_tag: Enum, listener: EventListener):
        self.c_add_listener(event_tag.value, listener)

    def remove_listener(self, event_tag: Enum, listener: EventListener):
        self.c_remove_listener(event_tag.value, listener)

    def get_listeners(self, event_tag: Enum) -> List[EventListener]:
        return self.c_get_listeners(event_tag.value)

    def trigger_event(self, event_tag: Enum, message: any):
        self.c_trigger_event(event_tag.value, message)

    cdef c_log_exception(self, int64_t event_tag, object arg):
        self.logger().error(f"Unexpected error while processing event {event_tag}.", exc_info=True)

    cdef c_add_listener(self, int64_t event_tag, EventListener listener):
        cdef:
            # 获取event_tag对应的事件迭代器
            EventsIterator it = self._events.find(event_tag)
            # event_tag对应的事件迭代器为空时用于初始化
            EventListenersCollection new_listeners
            # event_tag对应的事件集合指针
            EventListenersCollection *listeners_ptr
            # 定义listener的弱引用对象
            object listener_weakref = PyWeakref_NewRef(listener, None)
            # 定义listener的PyRef对象(自动处理引用计数)，内含listener的弱引用对象
            PyRef listener_wrapper = PyRef(<PyObject *>listener_weakref)
        # 向event_tag对应的事件集合添加listner
        if it != self._events.end():
            listeners_ptr = address(deref(it).second)
            deref(listeners_ptr).insert(listener_wrapper)
        # 初始化event_tag对应的事件迭代器集合
        else:
            new_listeners.insert(listener_wrapper)
            self._events.insert(EventsPair(event_tag, new_listeners))

        # 以ADD_LISTENER_GC_PROBABILITY概率执行检查和GC无引用的listener
        if random.random() < PubSub.ADD_LISTENER_GC_PROBABILITY:
            self.c_remove_dead_listeners(event_tag)

    cdef c_remove_listener(self, int64_t event_tag, EventListener listener):
        cdef:
            EventsIterator it = self._events.find(event_tag)
            EventListenersCollection *listeners_ptr
            object listener_weakref = PyWeakref_NewRef(listener, None)
            PyRef listener_wrapper = PyRef(<PyObject *>listener_weakref)
            EventListenersIterator lit
        if it == self._events.end():
            return
        listeners_ptr = address(deref(it).second)
        lit = deref(listeners_ptr).find(listener_wrapper)
        # 从event_tag对应的事件集合移除listner
        if lit != deref(listeners_ptr).end():
            deref(listeners_ptr).erase(lit)
        self.c_remove_dead_listeners(event_tag)

    cdef c_remove_dead_listeners(self, int64_t event_tag):
        cdef:
            EventsIterator it = self._events.find(event_tag)
            EventListenersCollection *listeners_ptr
            object listener_weakref
            EventListenersIterator lit
            vector[EventListenersIterator] lit_to_remove
        if it == self._events.end():
            return
        listeners_ptr = address(deref(it).second)
        lit = deref(listeners_ptr).begin()
        while lit != deref(listeners_ptr).end():
            # 通过deref(lit)获取listener的PyRef对象，再通过其get方法获取listener的PyWeakref对象
            listener_weakref = <object>(deref(lit).get())
            # 获取listner的PyObject对象,如果为空则加入lit_to_remove
            if <object>(PyWeakref_GetObject(listener_weakref)) is None:
                lit_to_remove.push_back(lit)
            # 否则迭代到下一个listener
            inc(lit)
        # 从event_tag对应的事件集合移除lit_to_remove中的listners
        for lit in lit_to_remove:
            deref(listeners_ptr).erase(lit)
        # event_tag对应的事件集合为空后，移除对应的EventsPair(event_tag, EventListenersCollection)
        if deref(listeners_ptr).size() < 1:
            self._events.erase(it)

    cdef c_get_listeners(self, int64_t event_tag):
        # 先清理lapsed(失效的)listeners
        self.c_remove_dead_listeners(event_tag)

        cdef:
            EventsIterator it = self._events.find(event_tag)
            EventListenersCollection *listeners_ptr
            object listener_weafref
            EventListener typed_listener

        if it == self._events.end():
            return []

        retval = []
        listeners_ptr = address(deref(it).second)
        for pyref in deref(listeners_ptr):
            # PyRef->PyWeekRef->PyObject
            listener_weafref = <object>pyref.get()
            typed_listener = <object>PyWeakref_GetObject(listener_weafref)
            retval.append(typed_listener)
        return retval

    cdef c_trigger_event(self, int64_t event_tag, object arg):
        # 先清理lapsed(失效的)listeners
        self.c_remove_dead_listeners(event_tag)

        cdef:
            EventsIterator it = self._events.find(event_tag)
            EventListenersCollection listeners
            object listener_weafref
            EventListener typed_listener
        if it == self._events.end():
            return

        # It is extremely important that this set of listeners is a C++ copy - because listeners are allowed to call
        # c_remove_listener(), which breaks the iterator if we're using the underlying set.
        listeners = deref(it).second
        for pyref in listeners:
            # PyRef->PyWeekRef->PyObject
            listener_weafref = <object>pyref.get()
            typed_listener = <object>PyWeakref_GetObject(listener_weafref)
            try:
                # 设置listener的event_tag和event_caller
                typed_listener.c_set_event_info(event_tag, self)
                # 再调用listener的call
                typed_listener.c_call(arg)
            except Exception:
                self.c_log_exception(event_tag, arg)
            finally:
                # 重置listener的event_tag和event_caller
                typed_listener.c_set_event_info(0, None)
