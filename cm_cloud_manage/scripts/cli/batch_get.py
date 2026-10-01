#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：batch_get"""
from __future__ import annotations

from cli.cli_runtime import (
    EXIT_OK,
    api_batch_get_all,
    emit_jsonl,
    emit_meta_and_files,
    enrich_file_list,
    exit_with_error,
    parse_batch_get_src_file,
    snapshot_trace_id,
)

def run(file_ids: list) -> int:
    try:
        batch_results = api_batch_get_all(file_ids, thumbnail_styles=['Small'])
    except RuntimeError as e:
        exit_with_error(f'查询失败: {e}')

    snapshot_trace_id()

    files, errors = [], []
    for item in batch_results:
        if item.get('errCode') != '0000':
            errors.append(f"errCode={item.get('errCode')} {item.get('message')}")
            continue
        src_file = parse_batch_get_src_file(item)
        if src_file:
            files.append(src_file)

    if errors:
        exit_with_error('\n'.join(errors))

    if not files:
        emit_jsonl({
            'record': 'meta', 'status': 'success', 'command': 'batch_get',
            'totalCount': 0,         })
        return EXIT_OK

    emit_meta_and_files('batch_get', len(files), enrich_file_list(files))
    return EXIT_OK
