#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 运行时 —— 退出码、JSONL/卡片输出、跨子命令共享展示逻辑（非子命令实现）。"""
from __future__ import annotations


import argparse
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from utils.config import (
    APP_NAME,
    BATCH_COPY_MOVE_MAX,
    BATCH_RENAME_MAX,
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
    FILE_PATH_AGGREGATE_COMMANDS,
    LIST_DISPLAY_LIMIT,
    MERGE_SEARCH_PAGE_SIZE,
    MCLAW_ALLOWED_DIR,
    MOVE_SKIP_OUTSIDE_MCLAW_PREFIX,
    SEARCH_CARD_DISPLAY_LIMIT,
    SEARCH_LIST_COMMANDS,
    SEARCH_TYPE_SEMANTIC_IMAGE,
    WRITE_COMMANDS,
)
from operation_log import (
    append_operation_log,
    build_operation_log_record,
    enriched_row_to_operation_log_record,
    get_operation_log_path_for_output,
    post_operation_file_id_from_batch_update,
    post_operation_file_id_from_task_row,
)
from services.atomic.folders import (
    classify_upload_parent_path,
    ensure_mclaw_dir_path,
)
from session_folder import ensure_default_session_upload_parent, query_default_session_folder
from mclaw.shared.organize.preview_cards import build_search_result_summary
from services.search_output_counts import (
    apply_search_counts_to_meta,
    build_search_counts,
    format_flat_top_message,
)
from services.atomic.client import (
    MERGE_SEARCH_PAGE_SIZE,
    SEARCH_IMAGE_PAGE_SIZE,
    _build_search_file_param_v3,
    api_batch_check_exists,
    api_batch_copy_async,
    api_batch_download_url,
    api_batch_file_update,
    api_batch_get,
    api_batch_get_all,
    api_batch_get_path,
    api_batch_move_async,
    api_check_exists,
    api_create_folder,
    api_file_complete,
    api_file_create,
    api_search_merge_file,
    normalize_page_after_input,
    page_after_to_cli_cursor,
    parse_batch_get_src_file,
)
from cli_trace import snapshot_trace_id
from utils import (
    clear_api_timings,
    command_uses_search_card_header,
    emit_file_list_card,
    emit_file_path_list_card,
    emit_image_list_card,
    emit_jsonl,
    format_bytes,
    init_operation_log,
    semantic_image_file_record,
    sha256_file,
)
from mclaw.shared.cm_cloud.cli_validate import (
    validate_cloud_file_ids,
    validate_cloud_parent_file_id as validate_cloud_parent_file_id_format,
)
from mclaw.shared.cm_cloud.session_cli_validate import (
    MclawEnvError,  # noqa: F401  # cli/* 透传使用
    normalize_cli_session_id,
    resolve_current_session,
)

from services.atomic.file_maps import get_file_info_map
from mclaw.shared.cm_cloud.file_enrichment import (
    enrich_file_list,
    enrich_listing_files,
    get_enriched_files_by_ids,
    hydrate_name_path_for_files,
)
from mclaw.shared.postprocess.paths import normalize_name_path
from mclaw.shared.postprocess.merge_normalize import is_result_row_successful, split_result_rows
from services.atomic.file_lookup import (
    batch_is_under_ai_space,
    get_file_path_map,
    get_single_file_info,
    get_single_file_path,
    is_under_ai_space,
)
from utils.helpers import normalize_rename_target_name
from mclaw.shared.postprocess.cli_rows import (
    collect_deduped_file_path_entries,
    enriched_row_to_cli_file_record,
    parent_dir_file_path,
)

build_search_file_param_v3 = _build_search_file_param_v3


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stdout)
        print(f'错误：{message}', file=sys.stdout, flush=True)
        print('提示：python3 main.py <子命令> -h 查看该子命令参数。', file=sys.stdout, flush=True)
        self.exit(EXIT_INPUT_ERROR)


def exit_with_error(
    message: str,
    *,
    code: int = EXIT_BUSINESS_ERROR,
    failed_api: Optional[str] = None,
    from_api: Optional[bool] = None,
    request: Optional[dict] = None,
) -> None:
    """终止进程并输出 error JSONL。

    from_api：为 True 时在 JSONL 中附带最近一次请求的 trace_id / failedApi；
    默认 None 表示由 code 推断：仅 BUSINESS（多为接口返回失败）附带 trace；INPUT / INTERNAL 默认不附带，除非显式 from_api=True。

    failed_api：显式传入时强制视为接口相关（启用上述附带信息）。
    request：接口请求入参，用于错误定位。
    """
    if failed_api:
        from_api = True
    if from_api is None:
        from_api = code == EXIT_BUSINESS_ERROR
    payload: dict = {'record': 'error', 'status': 'error', 'message': message}
    if from_api:
        payload['_from_api'] = True
    if failed_api:
        payload['failedApi'] = failed_api
    if request:
        payload['request'] = request
    emit_jsonl(payload)
    sys.exit(code)


def normalize_cloud_parent_file_id(raw: Optional[str]) -> str:
    """个人云父目录 ID：`/` 与 `root`（大小写不敏感）均表示根目录；否则校验云盘 fileId（33/44/45/49 位）。"""
    try:
        return validate_cloud_parent_file_id_format(raw or '', context='to_parent_file_id')
    except ValueError as e:
        exit_with_error(f'错误：{e}', code=EXIT_INPUT_ERROR)


    _ = (has_next_page, page_after, page_cursor, page_size)
    return dict(extra)


def emit_write_file_record(
    row: dict,
    *,
    index: int = 0,
    in_folder: Optional[bool] = None,
    parent_file_id: str = '',
    parent_file_name: str = '',
    write_operation_log: bool = True,
) -> dict[str, Any]:
    rec = enriched_row_to_cli_file_record(row, index=index)
    if write_operation_log:
        append_operation_log(
            enriched_row_to_operation_log_record(
                row,
                in_folder=in_folder,
                parent_file_id=parent_file_id,
                parent_file_name=parent_file_name,
            )
        )
    return rec


def collect_success_result_file_ids(
    rows: list[dict],
    *,
    require_new_file: bool,
) -> list[str]:
    """从复制/移动结果行收集应写入 <log_path> 日志的 fileId（成功项的操作后 fileId）。"""
    out: list[str] = []
    for row in rows:
        fid = post_operation_file_id_from_task_row(row, require_new_file=require_new_file)
        if fid:
            out.append(fid)
    return list(dict.fromkeys(out))


def emit_move_copy_write_records(
    ordered: list[dict],
    *,
    start_index: int = 1,
    operation_log_file_ids: set[str] | None = None,
    parent_file_id: str = '',
    parent_file_name: str = '',
    cli: str = '',
) -> None:
    """移动 / 复制 CLI：stdout 输出全部结果行；<log_path> 日志仅写入成功项的操作后 fileId。

    部分成功时仍须为每个成功 fileId 写入 dynamic_log；富化行缺失时会补查 batchGet。
    """
    enriched_by_id: dict[str, dict[str, Any]] = {}
    for row in ordered:
        fid = str(row.get('fileId') or '').strip()
        if fid:
            enriched_by_id[fid] = row

    log_ids: list[str] = []
    if operation_log_file_ids is not None:
        log_ids = list(dict.fromkeys(
            str(fid).strip() for fid in operation_log_file_ids if str(fid).strip()
        ))
        missing = [fid for fid in log_ids if fid not in enriched_by_id]
        if missing:
            for row in get_enriched_files_by_ids(missing, verbose=False):
                fid = str(row.get('fileId') or '').strip()
                if fid:
                    enriched_by_id[fid] = row

    file_rows: list[dict[str, Any]] = [
        enriched_row_to_cli_file_record(row, index=idx)
        for idx, row in enumerate(ordered, start=start_index)
    ]
    if file_rows:
        emit_file_list_card(file_rows, total=len(file_rows), search=False, cli=cli)

    if operation_log_file_ids is None:
        targets = [str(r.get('fileId') or '').strip() for r in ordered]
    else:
        targets = log_ids
    for fid in targets:
        if not fid:
            continue
        row = enriched_by_id.get(fid)
        if not row:
            continue
        append_operation_log(
            enriched_row_to_operation_log_record(
                row,
                in_folder=True,
                parent_file_id=parent_file_id,
                parent_file_name=parent_file_name,
            )
        )


def emit_meta_and_files(
    command: str,
    total_count: int,
    enriched_files: list,
    *,
    message: Optional[str] = None,
    warning: Optional[str] = None,
    page_after: Optional[Any] = None,
    next_page_cursor: Optional[str] = None,
    page_cursor: Optional[str] = None,
    meta_extra: Optional[Dict[str, Any]] = None,
    display_limit: Optional[int] = None,
    quality_top: Optional[int] = None,
    list_kind: str = 'file',
) -> None:
    """统一输出 meta 和 result list。"""
    limit = display_limit if display_limit is not None else LIST_DISPLAY_LIMIT
    if command in SEARCH_LIST_COMMANDS and quality_top is None:
        limit = min(limit, SEARCH_CARD_DISPLAY_LIMIT)
    display_rows = enriched_files[:limit]

    api_total = total_count
    after_select_filter = None
    if meta_extra:
        after_select_filter = meta_extra.get('afterSelectFilter')
    if quality_top is not None:
        message = message or format_flat_top_message(
            search_hits=api_total,
            displayed=len(display_rows),
            after_select_filter=after_select_filter,
        )
        total_count = len(display_rows)
    elif after_select_filter is not None:
        if message is None:
            if after_select_filter != api_total:
                message = f'检索命中 {api_total} 条，去重后 {after_select_filter} 条'
            else:
                message = f'检索命中 {api_total} 条'
        total_count = len(display_rows)
    elif message is None:
        message = f'检索命中 {total_count} 条'

    meta: Dict[str, Any] = {
        'record': 'meta',
        'status': 'success',
        'command': command,
        'totalCount': total_count,
        'message': message,
    }
    if quality_top is not None or after_select_filter is not None:
        counts = build_search_counts(
            search_hits=api_total,
            displayed=len(display_rows),
            after_select_filter=after_select_filter,
        )
        apply_search_counts_to_meta(meta, counts, include_api_total=True)
    if warning:
        meta['warning'] = warning
    if page_after is not None:
        meta['pageAfter'] = page_after
        cursor = page_after_to_cli_cursor(page_after)
        if cursor:
            meta['pageAfterCursor'] = cursor
    if next_page_cursor is not None:
        meta['nextPageCursor'] = next_page_cursor
    if page_cursor is not None:
        meta['pageCursor'] = page_cursor
    if meta_extra:
        meta.update(meta_extra)

    # filePathList 并入 meta 输出，不单独作为 filePaths 记录
    path_entries: list = []
    if command in FILE_PATH_AGGREGATE_COMMANDS:
        path_entries = collect_deduped_file_path_entries(enriched_files)

    if path_entries:
        meta['filePathList'] = path_entries

    emit_jsonl(meta)
    card_summary = build_search_result_summary(
        file_type='image' if list_kind == 'image' else 'file',
        total=api_total if quality_top is None else len(display_rows),
        shown=len(display_rows),
        top=int(quality_top or 0),
        phase='search',
    )
    if list_kind == 'image':
        image_rows = [
            semantic_image_file_record(row, index=idx)
            for idx, row in enumerate(display_rows, start=1)
        ]
        emit_image_list_card(
            image_rows,
            total=total_count,
            search=False if quality_top is not None else True,
            include_header=quality_top is None,
            cli=command,
            summary=card_summary,
        )
    else:
        file_rows = [
            enriched_row_to_cli_file_record(row, index=idx)
            for idx, row in enumerate(display_rows, start=1)
        ]
        emit_file_list_card(
            file_rows,
            total=total_count,
            search=False if quality_top is not None else command_uses_search_card_header(command),
            include_header=quality_top is None,
            cli=command,
            summary=card_summary,
        )
