#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 接口耗时采集与 stdout 缓冲。"""

from __future__ import annotations

import json
from typing import Any

from cm_cloud_auth import is_cm_cloud_debug

_api_timings: list[dict[str, Any]] = []
_api_failures: list[dict[str, Any]] = []
_cli_output_buffer: list[str] | None = None
_cli_output_tee: list[str] | None = None
_FAILAPI_MAX_ITEMS = 5


def clear_api_timings() -> None:
    """清空已记录的 HTTP 耗时与失败接口。"""
    global _api_timings, _api_failures
    _api_timings = []
    _api_failures = []


def record_api_timing(
    path: str,
    elapsed_ms: float,
    *,
    attempt: int = 0,
    max_attempts: int = 1,
    trace_id: str = '',
) -> None:
    """记录单次 HTTP 调用耗时。"""
    _api_timings.append(
        {
            'path': str(path or '').strip(),
            'elapsedMs': int(round(elapsed_ms)),
            'traceId': (trace_id or '').strip(),
        }
    )


def _short_api_path(path: str, *, max_len: int = 72) -> str:
    text = (path or '').strip()
    if not text:
        return text
    if len(text) <= max_len:
        return text
    parts = [part for part in text.split('/') if part]
    if len(parts) >= 2:
        for take in (4, 3, 2):
            tail = '/'.join(parts[-take:])
            if len(tail) <= max_len:
                return tail
    return text if len(text) <= max_len else text[-max_len:]


def _merge_api_timings() -> list[list[Any]]:
    """按 path 合并耗时；traceId 保留最后一次非空值，失败次数单独标记。"""
    order: list[str] = []
    totals: dict[str, int] = {}
    last_tid: dict[str, str] = {}
    fail_counts: dict[str, int] = {}
    for item in _api_timings:
        path = str(item.get('path') or '').strip()
        if not path:
            continue
        ms = int(item.get('elapsedMs') or 0)
        tid = str(item.get('traceId') or '').strip()
        if path not in totals:
            order.append(path)
            totals[path] = 0
        totals[path] += ms
        if tid:
            last_tid[path] = tid
        else:
            fail_counts[path] = fail_counts.get(path, 0) + 1
    return [
        [_short_api_path(path), totals[path],
         last_tid.get(path, ''),
         fail_counts.get(path, 0)]
        for path in order
    ]


def build_api_timing_record() -> dict[str, Any]:
    """构建 record=timing 的 JSONL 载荷。"""
    calls = _merge_api_timings()
    if not calls:
        return {}
    total_ms = sum(int(pair[1]) for pair in calls)
    return {
        'record': 'timing',
        'totalMs': total_ms,
        'calls': calls,
    }


def record_fail_api(
    api: str,
    message: str,
    *,
    request: Any = None,
    response: Any = None,
) -> None:
    """记录一次接口失败（供 flush 时输出 failapi，最多保留 5 条去重项）。

    ``request`` / ``response`` 为接口原始入参、出参（可选）。
    """
    api_path = _short_api_path(str(api or '').strip())
    error_text = str(message or '').strip()
    if not api_path or not error_text:
        return
    entry: dict[str, Any] = {'api': api_path, 'message': error_text}
    if request is not None:
        entry['request'] = request
    if response is not None:
        entry['response'] = response
    _api_failures.append(entry)


def build_failapi_record(*, limit: int = _FAILAPI_MAX_ITEMS) -> dict[str, Any]:
    """构建 record=failapi 的 JSONL 载荷。

    ``items`` 每项为 ``[api, message]``；若有入参/出参则为
    ``[api, message, request, response]``（缺省侧用空对象占位）。
    """
    if not _api_failures or limit <= 0:
        return {}
    items: list[list[Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in _api_failures:
        api_path = str(item.get('api') or '').strip()
        message = str(item.get('message') or '').strip()
        if not api_path or not message:
            continue
        key = (api_path, message)
        if key in seen:
            continue
        seen.add(key)
        row: list[Any] = [api_path, message]
        if 'request' in item or 'response' in item:
            row.append(item.get('request') if item.get('request') is not None else {})
            row.append(item.get('response') if item.get('response') is not None else {})
        items.append(row)
        if len(items) >= limit:
            break
    if not items:
        return {}
    return {
        'record': 'failapi',
        'items': items,
    }


def start_cli_output_buffer() -> None:
    """开启 stdout 缓冲，待 flush 时统一输出。"""
    global _cli_output_buffer
    _cli_output_buffer = []


def is_cli_output_buffering() -> bool:
    """stdout 缓冲是否开启（write_cli_output_line 暂存中）。"""
    return _cli_output_buffer is not None


def start_cli_output_tee() -> None:
    """开启 stdout tee：print 照常实时输出，同时收集全文供旁路落盘。

    与 ``start_cli_output_buffer`` 互斥语义（缓冲优先）：长跑命令需要
    进度/让出实时可见时用 tee，收尾 ``flush_cli_output_tee`` 取全文交
    ``append_mclaw_tool_result``。
    """
    global _cli_output_tee
    _cli_output_tee = []


def is_cli_output_teeing() -> bool:
    """stdout tee 是否开启（write_cli_output_line 实时 print 且收集中）。"""
    return _cli_output_tee is not None


def write_cli_output_line(line: str) -> None:
    """写入一行 CLI 输出（缓冲开启时暂存；tee 开启时实时 print 并收集；否则 print）。"""
    if _cli_output_buffer is not None:
        _cli_output_buffer.append(line)
    else:
        if _cli_output_tee is not None:
            _cli_output_tee.append(line)
        print(line, flush=True)


def flush_cli_output_tee() -> str:
    """返回 tee 收集的全文并复位（不打印；未开启或空时返回空字符串）。

    行间 ``\\n``、非空末尾带换行——与 ``flush_cli_output_buffer`` 返回值
    口径一致，供 ``append_mclaw_tool_result`` 旁路落盘。
    """
    global _cli_output_tee
    if _cli_output_tee is None:
        return ''
    collected = _cli_output_tee
    _cli_output_tee = None
    if not collected:
        return ''
    return '\n'.join(collected) + '\n'


def flush_cli_output_buffer(
    *,
    prepend_timing: bool | None = None,
    log_path: str | None = None,
    log_path_position: str = 'start',
) -> str:
    """刷出缓冲输出，并按调试配置前置 timing 行。

    返回实际刷出的完整文本：与 ``print`` 顺序一致，行间 ``\\n``，
    非空时末尾带换行（与真实 stdout 一致）。缓冲未开启时返回空字符串。
    """
    global _cli_output_buffer
    if _cli_output_buffer is None:
        return ''
    buffered = _cli_output_buffer
    _cli_output_buffer = None

    emitted: list[str] = []

    def _emit(line: str) -> None:
        print(line, flush=True)
        emitted.append(line)

    log_line = f'<log_path>{log_path}</log_path>' if log_path else None
    if log_path_position == 'start' and log_line:
        _emit(log_line)

    emit_timing = is_cm_cloud_debug() if prepend_timing is None else prepend_timing
    if emit_timing:
        timing = build_api_timing_record()
        if timing:
            _emit(json.dumps(timing, ensure_ascii=False))

    failapi = build_failapi_record()
    if failapi:
        _emit(json.dumps(failapi, ensure_ascii=False))

    for line in buffered:
        _emit(line)

    if log_path_position == 'end' and log_line:
        _emit(log_line)

    # toolresult 末尾追加 Agent 防复述说明（本次输出含 frontend_card 卡片时）；
    # 见 mclaw.shared.cm_cloud.card_meta.card_end_note
    try:
        from mclaw.shared.cm_cloud.card_meta import card_end_note
        end_note = card_end_note()
    except ImportError:
        end_note = ''
    if end_note:
        _emit(end_note)

    if not emitted:
        return ''
    return '\n'.join(emitted) + '\n'
