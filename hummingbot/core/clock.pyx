### 程序核心对象，管理程序时钟，驱动主要模块如connectors和strategies获取市场数据和触发交易行为
### 时间驱动是程序执行流的驱动来源之一，驱动定时执行任务；事件是另一个程序执行流的驱动来源，驱动EventListener(由PubSub管理)
# distutils: language=c++

import asyncio
import logging
import time
from typing import List

from hummingbot.core.time_iterator import TimeIterator
from hummingbot.core.time_iterator cimport TimeIterator
from hummingbot.core.clock_mode import ClockMode
from hummingbot.logger import HummingbotLogger

s_logger = None


cdef class Clock:
    """
    时钟类, 用于管理交易系统的时间流
    支持实时模式和回测模式
    """
    @classmethod
    def logger(cls) -> HummingbotLogger:
        """
        获取日志记录器
        """
        global s_logger
        if s_logger is None:
            s_logger = logging.getLogger(__name__)
        return s_logger

    def __init__(self, clock_mode: ClockMode, tick_size: float = 1.0, start_time: float = 0.0, end_time: float = 0.0):
        """
        :param clock_mode: either real time mode or back testing mode
        :param tick_size: time interval of each tick
        :param start_time: (back testing mode only) start of simulation in UNIX timestamp
        :param end_time: (back testing mode only) end of simulation in UNIX timestamp. NaN to simulate to end of data.
        """
        self._clock_mode = clock_mode
        self._tick_size = tick_size
        self._start_time = start_time if clock_mode is ClockMode.BACKTEST else (time.time() // tick_size) * tick_size
        self._end_time = end_time
        self._current_tick = self._start_time
        # 子迭代器, 元素是TimeIterator, 由回测模式使用
        self._child_iterators = []
        # 上下文，元素是TimeIterator, 由实时模式使用
        self._current_context = None
        self._started = False

    @property
    def clock_mode(self) -> ClockMode:
        """获取当前时钟模式"""
        return self._clock_mode

    @property
    def start_time(self) -> float:
        """获取开始时间"""
        return self._start_time

    @property
    def tick_size(self) -> float:
        """获取tick大小"""
        return self._tick_size

    @property
    def child_iterators(self) -> List[TimeIterator]:
        """获取子迭代器列表"""
        return self._child_iterators

    @property
    def current_timestamp(self) -> float:
        """获取当前时间戳"""
        return self._current_tick

    def __enter__(self) -> Clock:
        """
        上下文管理器入口, 用子迭代器列表初始化上下文
        用于管理时钟的上下文环境, 并不立即开始所有iterator
        """
        if self._current_context is not None:
            raise EnvironmentError("Clock context is not re-entrant.")
        self._current_context = self._child_iterators.copy()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        上下文管理器出口
        清理时钟上下文, 清理前先停止所有iterator
        """
        if self._current_context is not None:
            for iterator in self._current_context:
                (<TimeIterator>iterator).c_stop(self)
        self._current_context = None

    # 由？？？添加iterator
    def add_iterator(self, iterator: TimeIterator):
        """
        添加时间迭代器到_current_context和_child_iterators
        :param iterator: 要添加的时间迭代器, 如果已经开始, 则立刻触发传入的iterator
        """
        if self._current_context is not None:
            self._current_context.append(iterator)
        if self._started:
            (<TimeIterator>iterator).c_start(self, self._current_tick)
        self._child_iterators.append(iterator)

    def remove_iterator(self, iterator: TimeIterator):
        """
        移除时间迭代器
        :param iterator: 要移除的时间迭代器, 先停iterator再删
        """
        if self._current_context is not None and iterator in self._current_context:
            (<TimeIterator>iterator).c_stop(self)
            self._current_context.remove(iterator)
        self._child_iterators.remove(iterator)

    async def run(self):
        """
        运行时钟直到结束
        """
        await self.run_til(float("nan"))

    async def run_til(self, timestamp: float):
        """
        运行时钟直到指定时间戳, 按tick_size为时间间隔实时的调度上下文里的所有iterator
        param timestamp: 目标时间戳
        """
        cdef:
            TimeIterator child_iterator
            double now = time.time()
            double next_tick_time

        if self._current_context is None:
            raise EnvironmentError("run() and run_til() can only be used within the context of a `with...` statement.")

        self._current_tick = (now // self._tick_size) * self._tick_size

        # 如果还没开始则先开始上下文里的所有iterator
        if not self._started:
            for ci in self._current_context:
                child_iterator = ci
                child_iterator.c_start(self, self._current_tick)
            self._started = True

        try:
            while True:
                now = time.time()
                if now >= timestamp:
                    return

                # Sleep until the next tick
                next_tick_time = ((now // self._tick_size) + 1) * self._tick_size
                await asyncio.sleep(next_tick_time - now)
                # 休眠完成后更新当前tick时间
                self._current_tick = next_tick_time

                # Run through all the child iterators.
                for ci in self._current_context:
                    child_iterator = ci
                    try:
                        child_iterator.c_tick(self._current_tick)
                    except StopIteration:
                        self.logger().error("Stop iteration triggered in real time mode. This is not expected.")
                        return
                    except Exception:
                        self.logger().error("Unexpected error running clock tick.", exc_info=True)
        finally:
            for ci in self._current_context:
                child_iterator = ci
                child_iterator._clock = None

    def backtest_til(self, timestamp: float):
        """
        回测模式运行到指定时间戳, 不间断的跳过tick_size时间长度并调度子迭代器列表里的所有iterator
        :param timestamp: 目标时间戳
        """
        cdef TimeIterator child_iterator

        # 如果还没开始则先开始上下文里的所有iterator
        if not self._started:
            for ci in self._child_iterators:
                child_iterator = ci
                child_iterator.c_start(self, self._start_time)
            self._started = True

        try:
            while not (self._current_tick >= timestamp):
                # 更新当前tick时间为下个tick时间
                self._current_tick += self._tick_size
                # 直接运行子迭代器列表里的iterator
                for ci in self._child_iterators:
                    child_iterator = ci
                    try:
                        child_iterator.c_tick(self._current_tick)
                    except StopIteration:
                        raise
                    except Exception:
                        self.logger().error("Unexpected error running clock tick.", exc_info=True)
        except StopIteration:
            return
        finally:
            for ci in self._child_iterators:
                child_iterator = ci
                child_iterator._clock = None

    def backtest(self):
        """
        运行回测直到结束时间
        """
        self.backtest_til(self._end_time)
