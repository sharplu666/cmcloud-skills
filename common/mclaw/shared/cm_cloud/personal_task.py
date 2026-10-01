#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云 ``task/get`` 轮询：查询失败重试、任务终态与错误码映射。"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

# 查询失败连续次数上限（含首次）；超出则显式报错停止。
TASK_GET_MAX_FAILURES = 3
TASK_POLL_INTERVAL_SEC = 3.0
TASK_POLL_TIMEOUT_SEC = 60.0

TASK_STATUS_RUNNING = 'Running'
TASK_STATUS_SUCCEED = 'Succeed'
TASK_STATUS_PARTIAL = 'PartialSucceed'
TASK_STATUS_FAILED = 'Failed'

TASK_INFO_ERROR_MESSAGES = {
    '00010302': '文件密码不正确',
    '00010306': '文件总大小超过系统限制',
    '00010202': '资源配额不足',
    '00010010': '资源不存在',
    '00010305': '文件总数目超过系统限制',
    '00010014': '系统服务调用错误',
    '00010313': '文件层级超过系统限制',
    '00010316': '操作的文件总数超出用户限额',
    '00010317': '文件大小超过用户配额',
}


class PersonalTaskPollError(Exception):
    """task/get 查询失败、任务 Failed、或轮询超时。"""

    def __init__(
        self,
        message: str,
        *,
        task_id: str = '',
        code: str = '',
        status: str = '',
    ):
        super().__init__(message)
        self.task_id = task_id
        self.code = code
        self.status = status


def format_task_info_error(code: str, message: str) -> str:
    mapped = TASK_INFO_ERROR_MESSAGES.get(code)
    detail = mapped or (message or '').strip() or '异步任务失败'
    if code:
        return f'{detail}（code={code}）'
    return detail


def poll_personal_task(
    task_id: str,
    *,
    get_fn: Callable[[str], Optional[Dict[str, Any]]],
    interval_sec: float = TASK_POLL_INTERVAL_SEC,
    timeout_sec: float = TASK_POLL_TIMEOUT_SEC,
    max_query_failures: int = TASK_GET_MAX_FAILURES,
) -> Dict[str, Any]:
    """轮询 ``task/get`` 直至 Succeed / PartialSucceed。

    ``get_fn(task_id)`` 应对齐 ``personal_service.task_get``：成功返回 data，
    查询失败返回 ``None``（不抛）。连续 ``None`` 达到 ``max_query_failures`` 则抛错。
    """
    tid = str(task_id or '').strip()
    if not tid:
        raise PersonalTaskPollError('异步任务 ID 为空，无法查询进度')

    last_data: Optional[Dict[str, Any]] = None
    deadline = time.monotonic() + float(timeout_sec)
    query_failures = 0
    first = True
    while time.monotonic() < deadline:
        if not first:
            time.sleep(float(interval_sec))
        first = False
        data = get_fn(tid)
        if data is None:
            query_failures += 1
            if query_failures >= int(max_query_failures):
                raise PersonalTaskPollError(
                    f'查询任务失败，已重试 {int(max_query_failures)} 次（taskId={tid}）',
                    task_id=tid,
                )
            continue
        query_failures = 0
        last_data = data
        info = data.get('taskInfo') or {}
        status = str(info.get('status') or '').strip()
        ti_code = str(info.get('code') or '').strip()
        ti_message = str(info.get('message') or '').strip()
        if status == TASK_STATUS_FAILED or (ti_code and ti_code != '0000'):
            raise PersonalTaskPollError(
                format_task_info_error(ti_code, ti_message),
                task_id=tid,
                code=ti_code,
                status=status or TASK_STATUS_FAILED,
            )
        if status in (TASK_STATUS_SUCCEED, TASK_STATUS_PARTIAL):
            return last_data

    if last_data is None:
        raise PersonalTaskPollError(f'查询任务失败（taskId={tid}）', task_id=tid)

    status = str((last_data.get('taskInfo') or {}).get('status') or '').strip()
    raise PersonalTaskPollError(
        f'任务超时，请稍后重试（taskId={tid}）',
        task_id=tid,
        status=status or TASK_STATUS_RUNNING,
    )


__all__ = [
    'PersonalTaskPollError',
    'TASK_GET_MAX_FAILURES',
    'TASK_INFO_ERROR_MESSAGES',
    'TASK_POLL_INTERVAL_SEC',
    'TASK_POLL_TIMEOUT_SEC',
    'TASK_STATUS_FAILED',
    'TASK_STATUS_PARTIAL',
    'TASK_STATUS_RUNNING',
    'TASK_STATUS_SUCCEED',
    'format_task_info_error',
    'poll_personal_task',
]
