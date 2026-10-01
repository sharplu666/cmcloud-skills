#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程退出时的 stdout 标记输出。

集中管理所有 ``atexit`` 钩子向 stdout 输出的标记，便于上层 CLI 感知本次
运行的辅助信息。每个钩子独立函数 + 独立 try/except，单个失败不影响其它。

当前注册的钩子：

1. ``_print_ai_space_log_path`` —— 输出 ``<log_path>...</log_path>`` 标记，
   供 CLI 上层感知 AI 空间日志文件位置。仅当 ``_ai_space_log`` 已写入至少
   一条记录时输出。
2. ``_print_request_id_debug`` —— 输出 ``<debug>requestId=...</debug>`` 标记，
   供 CLI 上层获取本次进程的全局 requestId（``GlobalLogInfoSettings.REQUEST_ID``），
   用于关联本次运行的所有 status_log 日志条目。
3. ``_print_total_elapsed`` —— 通过 ``status_log`` 输出本次 Python 进程的
   整体耗时（自本模块被加载即 ``import mclaw`` 起算，至进程退出）。

注册入口：``mclaw/__init__.py`` 调用 ``register_exit_hooks()``。
"""

from __future__ import annotations

import atexit
import time


# mclaw 内部计时器起点：本模块在 ``mclaw/__init__.py`` 首行即被导入，
# 故此值近似等于 ``import mclaw`` 的时刻。用 perf_counter 取单调高精度时钟，
# 规避系统时钟回拨。
_START_TIME = time.perf_counter()


__all__ = ['register_exit_hooks']


def _print_ai_space_log_path() -> None:
    """打印 ``<log_path>`` 标记（仅当已写入记录）。

    若一次进程内写入了多个日志文件（如 organize 同时触发 album_add 与
    album_file_add），则按写入顺序逐行输出多个 ``<log_path>`` 标记。
    """
    try:
        from mclaw.api.base._ai_space_log import get_ai_space_log_path_for_output
    except Exception:
        return
    paths = get_ai_space_log_path_for_output()
    for path in paths:
        if path:
            print(f'<log_path>{path}</log_path>', flush=True)


def _print_request_id_debug() -> None:
    """打印 ``<debug>requestId=...</debug>`` 标记。

    输出本次进程的全局 requestId（``GlobalLogInfoSettings.REQUEST_ID``），
    供 CLI 上层关联本次运行的所有 status_log 日志条目。
    """
    try:
        from mclaw.utils.settings import GlobalLogInfoSettings
        print(f'<debug>requestId={GlobalLogInfoSettings.REQUEST_ID}</debug>', flush=True)
    except Exception:
        return


def _print_total_elapsed() -> None:
    """通过 ``status_log`` 输出本次 Python 进程的整体耗时。

    计时区间：``import mclaw``（本模块加载，即 ``_START_TIME``）→ 进程退出
    （本钩子执行）。``atexit`` 钩子按注册逆序执行，本钩子先于
    ``_print_request_id_debug`` 注册故后执行，但 requestId 已在模块加载时
    确定，故此处仍可正常关联。
    """
    try:
        from mclaw.utils.logger import status_log
        elapsed_ms = int((time.perf_counter() - _START_TIME) * 1000)
        status_log(
            msg=f'[mclaw]进程整体耗时 elapsed_ms={elapsed_ms}',
            info_dict={'elapsed_ms': elapsed_ms, 'stage': 'process_exit'},
            server_type='MCLAW',
        )
    except Exception:
        return


def register_exit_hooks() -> None:
    """注册所有退出钩子到 ``atexit``。

    由 ``mclaw/__init__.py`` 调用一次，避免重复注册。

    ``atexit`` 钩子按注册的逆序（LIFO）执行：先输出 ``<log_path>`` /
    ``<debug>requestId`` 标记，最后输出整体耗时 status_log，确保耗时
    覆盖到所有前置钩子。
    """
    atexit.register(_print_ai_space_log_path)
    atexit.register(_print_request_id_debug)
    atexit.register(_print_total_elapsed)
