import asyncio
import logging
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Tuple

from hummingbot.core.api_throttler.data_types import RateLimit, TaskLog
from hummingbot.logger.logger import HummingbotLogger

arc_logger = None
MAX_CAPACITY_REACHED_WARNING_INTERVAL = 30.0


class AsyncRequestContextBase(ABC):
    """
    An async context class ('async with' syntax) that checks for rate limit and waits for the capacity to be freed.
    It uses an async lock to prevent multiple instances of this class from accessing the `acquire()` function.
    作为context对象, 管理并判断是否允许新API Request发送, 确保不超过其RateLimit
    """

    _last_max_cap_warning_ts: float = 0.0

    @classmethod
    def logger(cls) -> HummingbotLogger:
        global arc_logger
        if arc_logger is None:
            arc_logger = logging.getLogger(__name__)
        return arc_logger

    def __init__(self,
                 task_logs: List[TaskLog],
                 rate_limit: RateLimit,
                 related_limits: List[Tuple[RateLimit, int]],
                 lock: asyncio.Lock,
                 safety_margin_pct: float,
                 retry_interval: float = 0.1,
                 ):
        """
        Asynchronous context associated with each API request.
        :param task_logs: Shared task logs associated with this API request
        :param rate_limit: The RateLimit associated with this API Request
        :param related_limits: List of linked rate limits with its corresponding weight associated with this API Request
        :param lock: A shared asyncio.Lock used between all instances of APIRequestContextBase
        :param retry_interval: Time between each limit check
        """
        self._task_logs: List[TaskLog] = task_logs
        self._rate_limit: RateLimit = rate_limit
        self._related_limits: List[Tuple[RateLimit, int]] = related_limits
        self._lock: asyncio.Lock = lock
        self._safety_margin_pct: float = safety_margin_pct
        self._retry_interval: float = retry_interval

    def flush(self):
        """
        Remove task logs that have passed rate limit periods
        将不在当前限流周期内的老request从_task_log中释放掉
        :return:
        """
        now: Decimal = Decimal(str(time.time()))
        for task in self._task_logs:
            task_limit: RateLimit = task.rate_limit
            elapsed: Decimal = now - Decimal(str(task.timestamp))
            if elapsed > Decimal(str(task_limit.time_interval * (1 + self._safety_margin_pct))):
                self._task_logs.remove(task)

    @abstractmethod
    def within_capacity(self) -> bool:
        raise NotImplementedError

    # 循环判断当前是否可以再容纳新的request直到等到可以容纳
    async def acquire(self):
        while True:
            async with self._lock:
                self.flush()

                if self.within_capacity():
                    break
            await asyncio.sleep(self._retry_interval)
        async with self._lock:
            now = time.time()
            # Each related limit is represented as it own individual TaskLog

            # Log the acquired rate limit into the tasks log
            self._task_logs.append(TaskLog(timestamp=now,
                                           rate_limit=self._rate_limit,
                                           weight=self._rate_limit.weight))

            # Log its related limits into the tasks log as individual tasks
            for limit, weight in self._related_limits:
                self._task_logs.append(TaskLog(timestamp=now, rate_limit=limit, weight=weight))

    # with语句执行时执行此方法
    # 如在RestAssistant.execute_request_and_get_response中调用call request之前有：
    # async with self._throttler.execute_task(limit_id=throttler_limit_id))，此语句初始化AsyncRequestContext对象(并执行此方法)
    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        pass
