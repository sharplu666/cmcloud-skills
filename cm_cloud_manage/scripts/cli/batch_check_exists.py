#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：batch_check_exists"""
from __future__ import annotations

from cli.cli_runtime import (
    Any,
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    api_batch_check_exists,
    collect_deduped_file_path_entries,
    emit_file_list_card,
    emit_jsonl,
    enriched_row_to_cli_file_record,
    exit_with_error,
    get_enriched_files_by_ids,
    normalize_cloud_parent_file_id,
    snapshot_trace_id,
)

def compact_check_exists_file_name(name: str) -> str:
    """去掉名称中的全部空白字符（含半角/全角空格、制表符等），用于存在性检查的兜底匹配。"""
    return ''.join(ch for ch in str(name or '') if not ch.isspace())

def _parse_batch_check_exists_response(row: dict) -> tuple[str, str, bool, str, str]:
    code = str(row.get('code') or '').strip()
    msg = str(row.get('message') or '').strip()
    data = row.get('data') if isinstance(row.get('data'), dict) else {}
    exists = bool(data.get('exist'))
    file_id = str(data.get('appFileId') or '').strip()
    file_type = str(data.get('fileType') or '').strip()
    return code, msg, exists, file_id, file_type

def parse_check_exists_spec(token: str) -> tuple[str, str]:
    t = token.strip()
    sep = ':' if ':' in t else ('：' if '：' in t else None)
    if sep is None:
        exit_with_error(
            '错误：每项须为 parentFileId:fileName 格式（支持中英文冒号）',
            code=EXIT_INPUT_ERROR,
        )
    parent_file_id, _, file_name = t.partition(sep)
    parent_file_id = normalize_cloud_parent_file_id(parent_file_id.strip())
    file_name = file_name.strip()
    if not parent_file_id or not file_name:
        exit_with_error('错误：parentFileId 与 fileName 均不能为空', code=EXIT_INPUT_ERROR)
    return parent_file_id, file_name

def parse_check_exists_specs(raw_specs: list[str]) -> list[tuple[str, str]]:
    tokens: list[str] = []
    for raw in raw_specs:
        normalized = str(raw or '').replace('，', ',')
        tokens.extend(x.strip() for x in normalized.split(',') if x.strip())
    if not tokens:
        exit_with_error('错误：至少提供一项 parentFileId:fileName', code=EXIT_INPUT_ERROR)
    return [parse_check_exists_spec(t) for t in tokens]

def run(
    checks: list[tuple[str, str]],
) -> int:
    sub_requests = [
        {'id': str(i), 'parentFileId': parent_file_id, 'fileName': file_name}
        for i, (parent_file_id, file_name) in enumerate(checks)
    ]
    try:
        rows = api_batch_check_exists(sub_requests)
    except RuntimeError as e:
        exit_with_error(f'批量检查失败: {e}')

    check_records: list[dict[str, Any]] = []
    retry_targets: list[tuple[int, str, str]] = []

    for i, (parent_file_id, file_name) in enumerate(checks):
        rid = str(i)
        code, msg, exists, file_id, file_type = _parse_batch_check_exists_response(rows.get(rid) or {})
        record: dict[str, Any] = {
            'record': 'check',
            'command': 'batch_check_exists',
            'requestId': rid,
            'parentFileId': parent_file_id,
            'fileName': file_name,
            'exist': exists,
            'fileId': file_id,
            'fileType': file_type,
            'errCode': code or '0000',
            'message': msg,
        }
        check_records.append(record)

        if code == '0000' and not exists and any(ch.isspace() for ch in file_name):
            compact_name = compact_check_exists_file_name(file_name)
            if compact_name and compact_name != file_name:
                retry_targets.append((i, parent_file_id, compact_name))

    if retry_targets:
        retry_requests = [
            {'id': str(j), 'parentFileId': parent, 'fileName': compact_name}
            for j, (_, parent, compact_name) in enumerate(retry_targets)
        ]
        try:
            retry_rows = api_batch_check_exists(retry_requests)
        except RuntimeError as e:
            exit_with_error(f'批量检查失败（去空格重试）: {e}')

        for j, (orig_i, parent_file_id, compact_name) in enumerate(retry_targets):
            code, msg, exists, file_id, file_type = _parse_batch_check_exists_response(
                retry_rows.get(str(j)) or {}
            )
            if code != '0000' or not exists:
                continue
            record = check_records[orig_i]
            record['exist'] = True
            record['fileId'] = file_id
            record['fileType'] = file_type
            record['matchedFileName'] = compact_name
            record['nameFallback'] = 'strip_whitespace'
            if msg:
                record['message'] = msg

    snapshot_trace_id()

    exist_file_ids: list[str] = []
    exist_count = missing_count = error_count = 0
    for record in check_records:
        code = str(record.get('errCode') or '').strip()
        if code != '0000':
            error_count += 1
        elif record.get('exist'):
            exist_count += 1
            fid = str(record.get('fileId') or '').strip()
            if fid:
                exist_file_ids.append(fid)
        else:
            missing_count += 1

    total = len(checks)
    if error_count == 0:
        status = 'success'
    elif error_count == total:
        status = 'error'
    else:
        status = 'warning'

    unique_exist_ids = list(dict.fromkeys(exist_file_ids))
    ordered: list[dict] = []
    path_entries: list[dict] = []
    if unique_exist_ids:
        enriched = get_enriched_files_by_ids(unique_exist_ids)
        by_id = {str(r.get('fileId') or '').strip(): r for r in enriched}
        ordered = [by_id[fid] for fid in unique_exist_ids if fid in by_id]
        path_entries = collect_deduped_file_path_entries(ordered)

    meta_payload: dict[str, Any] = {
        'record': 'meta',
        'status': status,
        'command': 'batch_check_exists',
        'totalCount': total,
        'existCount': exist_count,
        'missingCount': missing_count,
        'errorCount': error_count,
        'message': f'批量检查完成：存在 {exist_count}，不存在 {missing_count}，失败 {error_count}',
    }
    if path_entries:
        meta_payload['filePathList'] = path_entries
    emit_jsonl(meta_payload)
    for idx, item in enumerate(check_records, start=1):
        if isinstance(item, dict) and 'index' not in item:
            item = {**item, 'index': idx}
        emit_jsonl(item)
    if ordered:
        file_rows = [
            enriched_row_to_cli_file_record(row, index=idx)
            for idx, row in enumerate(ordered, start=1)
        ]
        emit_file_list_card(file_rows, total=len(file_rows), search=False, cli='batch_check_exists')

    return EXIT_OK if error_count == 0 else EXIT_BUSINESS_ERROR
