#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 CLI JSONL 输出：字段序、trace_id、failedApi。

各 skill 通过 ``write_line=write_cli_output_line`` 写入 stdout 缓冲。
依赖 ``common_auth`` 的 ``cli_trace`` / ``cli_timing``（运行前须已加入 ``sys.path``）。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

WriteLine = Callable[[str], None]


def _default_write_line(line: str) -> None:
    from cli_timing import write_cli_output_line

    write_cli_output_line(line)


def order_jsonl_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """按约定字段序组装 JSONL 对象，并注入 trace_id / failedApi。"""
    from cli_trace import get_last_api_path, get_last_trace_id, meta_trace_id

    ordered: Dict[str, Any] = {}
    rec = payload.get('record')
    if rec == 'meta':
        tid = meta_trace_id()
        if tid:
            ordered['trace_id'] = tid
    elif rec == 'error' and payload.get('_from_api'):
        tid = get_last_trace_id()
        if tid:
            ordered['trace_id'] = tid
        ap = payload.get('failedApi') or get_last_api_path()
        if ap:
            ordered['failedApi'] = ap
    for key in ('record', 'status', 'command', 'message'):
        if key in payload:
            ordered[key] = payload[key]
    for key, val in payload.items():
        if key not in ordered and key != '_from_api':
            ordered[key] = val
    return ordered


def emit_jsonl(
    payload: Dict[str, Any],
    *,
    write_line: Optional[WriteLine] = None,
) -> None:
    """输出一行 JSONL 至 stdout（或缓冲）。"""
    writer = write_line or _default_write_line
    writer(json.dumps(order_jsonl_payload(payload), ensure_ascii=False))


def build_error_payload(
    message: str,
    *,
    code: int = 2,
    from_api: Optional[bool] = None,
    failed_api: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 ``record=error`` JSONL 载荷（未序列化）。"""
    if failed_api:
        from_api = True
    if from_api is None:
        from_api = code == 2
    payload: Dict[str, Any] = {
        'record': 'error',
        'status': 'error',
        'message': message,
    }
    if from_api:
        payload['_from_api'] = True
    if failed_api:
        payload['failedApi'] = failed_api
    return payload


def emit_error(
    message: str,
    *,
    code: int = 2,
    from_api: Optional[bool] = None,
    failed_api: Optional[str] = None,
    write_line: Optional[WriteLine] = None,
) -> int:
    """输出 error JSONL 并返回退出码（不调用 ``sys.exit``）。"""
    emit_jsonl(
        build_error_payload(
            message,
            code=code,
            from_api=from_api,
            failed_api=failed_api,
        ),
        write_line=write_line,
    )
    return code


__all__ = [
    'WriteLine',
    'build_error_payload',
    'emit_error',
    'emit_jsonl',
    'order_jsonl_payload',
]
