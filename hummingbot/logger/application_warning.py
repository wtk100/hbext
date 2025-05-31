#!/usr/bin/env python

from typing import (
    NamedTuple,
    Tuple,
    Optional
)


# 定义程序Warning信息的结构，用于logging
class ApplicationWarning(NamedTuple):
    timestamp: float
    logger_name: str
     # 文件名、行号、函数、堆栈
    caller_info: Tuple[str, int, str, Optional[str]]
    warning_msg: str

    @property
    def filename(self) -> str:
        return self.caller_info[0]

    @property
    def line_number(self) -> int:
        return self.caller_info[1]

    @property
    def function_name(self) -> str:
        return self.caller_info[2]

    @property
    def stack_info(self) -> Optional[str]:
        return self.caller_info[3]
