#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 请求级可观测性状态 —— trace_id / 接口路径 / 主接口上下文。

供各 skill 共享：原始 HTTP 调用方用 ``set_last_trace_id(response)`` 登记响应头中的
trace；common ``mclaw.api`` 调用方用 ``capture_trace_string(trace)`` 登记其响应的 trace
串。两者写入同一组进程级全局状态，``meta`` 输出与失败 JSONL 统一从此处读取。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional, Tuple

import requests

_last_trace_id: str = ''
_last_yun_tid: str = ''
_command_trace_id: str = ''
_last_api_path: str = ''
_primary_search_type: str = ''
_primary_request_payload: Dict[str, Any] = {}


def set_last_trace_id(response: Optional[requests.Response]) -> None:
    """登记 ``requests.Response`` 响应头中的 trace_id 与 x-yun-tid。"""
    global _last_trace_id, _last_yun_tid
    if response is None:
        return
    tid = (response.headers.get('trace_id') or '').strip()
    if tid:
        _last_trace_id = tid
    ytid = (response.headers.get('x-yun-tid') or '').strip()
    if ytid:
        _last_yun_tid = ytid


def capture_trace_string(trace: str) -> None:
    """登记 common ``mclaw.api`` 响应的 trace 串（``trace_id=xxx`` / ``x-yun-tid=yyy``）。"""
    global _last_trace_id, _last_yun_tid
    text = str(trace or '').strip()
    if text.startswith('trace_id='):
        _last_trace_id = text[len('trace_id='):].strip()
    elif text.startswith('x-yun-tid='):
        _last_yun_tid = text[len('x-yun-tid='):].strip()


def get_last_trace_id() -> str:
    return _last_trace_id


def get_last_yun_tid() -> str:
    return _last_yun_tid


def snapshot_trace_id() -> None:
    """快照当前 trace_id 为命令级 trace（供 meta 输出）。"""
    global _command_trace_id
    _command_trace_id = _last_trace_id


def get_command_trace_id() -> str:
    return _command_trace_id


def meta_trace_id() -> str:
    return (get_command_trace_id() or get_last_trace_id()).strip()


def clear_last_trace_id() -> None:
    """清空最近 trace / yun-tid / 命令级快照，避免跨请求或跨用例污染。"""
    global _last_trace_id, _last_yun_tid, _command_trace_id
    _last_trace_id = ''
    _last_yun_tid = ''
    _command_trace_id = ''


def set_last_api_path(path: str) -> None:
    """登记当前（或刚失败）请求的接口 path，如 /richlifeApp/...，用于失败 JSONL 的 failedApi。"""
    global _last_api_path
    p = (path or '').strip()
    _last_api_path = ('' if not p else (p if p.startswith('/') else '/' + p.lstrip('/')))


def get_last_api_path() -> str:
    return _last_api_path


def set_primary_api_context(search_type: str, request_payload: Dict[str, Any]) -> None:
    """登记主接口 searchType 与原始请求体（富化接口不得覆盖）。"""
    global _primary_search_type, _primary_request_payload
    _primary_search_type = str(search_type or '').strip()
    _primary_request_payload = copy.deepcopy(request_payload or {})


def get_primary_api_context() -> Tuple[str, Dict[str, Any]]:
    """返回 (searchType, requestPayload)，含完整请求参数（包括分页）。"""
    return _primary_search_type, copy.deepcopy(_primary_request_payload or {})


def attach_primary_api_meta(meta: Dict[str, Any]) -> None:
    search_type, payload = get_primary_api_context()
    if search_type:
        meta['requestPayload'] = payload
