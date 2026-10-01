#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Service 层可观测性收尾 —— 登记接口 path / 捕获 trace。

HTTP 耗时由 ``mclaw.api.base._http.post_json_with_retry`` 统一记录。
依赖运行时 ``sys.path`` 已包含 ``common_auth``（``cli_trace``）。
"""

from __future__ import annotations

from typing import Any

from cli_trace import capture_trace_string, set_last_api_path


def http_path(path: str) -> str:
    """规范化为以 ``/`` 开头的 HTTP path。"""
    return '/' + str(path or '').strip().lstrip('/')


def finish(path: str, started: float, response: Any) -> Any:
    """登记接口 path、捕获 trace。

    ``started`` 仅为兼容旧调用保留，耗时由 ``post_json_with_retry`` 记录。
    """
    _ = started
    set_last_api_path(path)
    capture_trace_string(getattr(response, 'trace_id', '') or '')
    return response


def err_message(response: Any, default: str) -> str:
    """取响应 ``message``；空则回退 ``default``。"""
    msg = str(getattr(response, 'message', '') or '').strip()
    return msg or default


def data_dict(response: Any) -> dict:
    """从响应 ``raw.data`` 取字典；缺失时返回空 dict。"""
    return (getattr(response, 'raw', None) or {}).get('data') or {}


__all__ = [
    'http_path',
    'finish',
    'err_message',
    'data_dict',
]
