#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：get_path"""
from __future__ import annotations

from cli.cli_runtime import (
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    api_batch_get_path,
    emit_jsonl,
    exit_with_error,
    normalize_name_path,
    snapshot_trace_id,
)
from mclaw.shared.postprocess.paths import normalize_name_path

def run(file_ids: list) -> int:
    if not file_ids:
        exit_with_error('错误：file_ids 不能为空', code=EXIT_INPUT_ERROR)
    if len(file_ids) > 100:
        exit_with_error('错误：单次最多 100 个 fileId', code=EXIT_INPUT_ERROR)

    try:
        items = api_batch_get_path(file_ids)
    except RuntimeError as e:
        exit_with_error(f'查询路径失败: {e}')

    snapshot_trace_id()

    if not items:
        emit_jsonl({
            'record': 'meta',
            'status': 'success',
            'command': 'get_path',
            'totalCount': 0,
                        'message': '查询结果为空',
        })
        return EXIT_OK

    ok_count = sum(1 for row in items if str(row.get('errCode') or '0000') == '0000')
    fail_count = len(items) - ok_count
    status = 'success' if fail_count == 0 else ('error' if ok_count == 0 else 'warning')
    emit_jsonl({
        'record': 'meta',
        'status': status,
        'command': 'get_path',
        'totalCount': len(items),
        'okCount': ok_count,
        'failCount': fail_count,
        'message': f'路径查询完成：成功 {ok_count}，失败 {fail_count}',
    })
    for idx, row in enumerate(items, start=1):
        emit_jsonl({
            'record': 'path',
            'index': idx,
            'fileId': row.get('fileId', ''),
            'filePath': normalize_name_path(row.get('namePath', '')),
            'idPath': row.get('idPath', ''),
            'type': row.get('type', ''),
            'errCode': row.get('errCode'),
            'message': row.get('message'),
        })
    return EXIT_OK if fail_count == 0 else EXIT_BUSINESS_ERROR
