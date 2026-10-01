#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：batch_copy"""
from __future__ import annotations

from cli.cli_runtime import (
    Any,
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    MCLAW_ALLOWED_DIR,
    append_operation_log,
    collect_deduped_file_path_entries,
    collect_success_result_file_ids,
    emit_file_path_list_card,
    emit_jsonl,
    emit_move_copy_write_records,
    enriched_row_to_operation_log_record,
    exit_with_error,
    get_enriched_files_by_ids,
    get_single_file_info,
    get_single_file_path,
    is_under_ai_space,
    os,
    snapshot_trace_id,
)
from services.atomic.batch_ops import batch_copy_to_parent_file_id

def run(
    file_ids: list,
    to_parent_file_id: str,
    _session: str = '',
) -> int:
    # 位置参数 session 仅兼容保留，复制目标由 to_parent_file_id 决定
    _ = _session
    try:
        normalized_file_ids = [str(fid or '').strip() for fid in file_ids if str(fid or '').strip()]
        if not normalized_file_ids:
            exit_with_error('批量复制失败：file_ids 不能为空', code=EXIT_INPUT_ERROR)

        normalized_target_parent_file_id = str(to_parent_file_id or '').strip()
        if not normalized_target_parent_file_id:
            exit_with_error('批量复制失败：to_parent_file_id 不能为空', code=EXIT_INPUT_ERROR)

        target_info = get_single_file_info(normalized_target_parent_file_id, action='复制文件')
        target_type = str(target_info.get('type') or '').strip().lower()
        target_category = str(target_info.get('category') or '').strip().lower()
        if target_type not in ('folder', '2') and target_category != 'folder':
            exit_with_error(
                f'批量复制失败：to_parent_file_id={normalized_target_parent_file_id} 不是文件夹',
                code=EXIT_INPUT_ERROR,
                from_api=False,
            )

        if not is_under_ai_space(normalized_target_parent_file_id):
            exit_with_error(
                f'批量复制失败：本技能仅允许复制到「{MCLAW_ALLOWED_DIR}」，'
                f'无法在云盘其它位置执行复制（to_parent_file_id: {normalized_target_parent_file_id}）',
                code=EXIT_INPUT_ERROR,
                from_api=False,
            )

        target_path = get_single_file_path(normalized_target_parent_file_id, action='复制文件')

        rows = batch_copy_to_parent_file_id(
            normalized_file_ids,
            normalized_target_parent_file_id,
            command='batch_copy.copy_files',
        )
        if not rows:
            exit_with_error('批量复制失败：复制待复制文件到目标目录失败')
    except (RuntimeError, ValueError) as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR, from_api=True)

    snapshot_trace_id()

    ok_count = sum(1 for row in rows if str(row.get('errCode') or '') == '0000')
    fail_count = len(rows) - ok_count
    is_success = fail_count == 0
    status = 'success' if fail_count == 0 else ('error' if ok_count == 0 else 'warning')
    message = '批量复制成功' if fail_count == 0 else ('批量复制失败' if ok_count == 0 else '批量复制部分成功')
    copied_file_ids = [
        str(row.get('newFileId') or '').strip()
        for row in rows
        if str(row.get('errCode') or '') == '0000' and str(row.get('newFileId') or '').strip()
    ]
    enriched = get_enriched_files_by_ids(copied_file_ids)
    by_id = {str(r.get('fileId') or '').strip(): r for r in enriched}
    ordered = [by_id[fid] for fid in copied_file_ids if fid in by_id]

    # 显式写入操作日志：直接用 batchGet 富化结果，避免 emit_move_copy_write_records
    # 中 collect_success_result_file_ids(require_new_file=True) 因 newFileId==oldFileId 返回空
    parent_folder_name = os.path.basename(target_path.rstrip('/')) or target_path
    for fid in copied_file_ids:
        row = by_id.get(fid)
        if row:
            append_operation_log(
                enriched_row_to_operation_log_record(
                    row,
                    in_folder=True,
                    parent_file_id=normalized_target_parent_file_id,
                    parent_file_name=parent_folder_name,
                )
            )

    path_entries = collect_deduped_file_path_entries(ordered)

    meta_payload: dict[str, Any] = {
        'record': 'meta',
        'status': status,
        'command': 'batch_copy',
        'message': message,
        'targetFolderFileId': normalized_target_parent_file_id,
        'targetFolderPath': target_path,
        'okCount': ok_count,
        'failCount': fail_count,
    }
    if path_entries:
        meta_payload['filePathList'] = path_entries
    emit_jsonl(meta_payload)

    emit_move_copy_write_records(
        ordered,
        operation_log_file_ids=set(
            collect_success_result_file_ids(rows, require_new_file=True)
        ),
        parent_file_id=normalized_target_parent_file_id,
        parent_file_name=os.path.basename(target_path.rstrip('/')) or target_path,
        cli='batch_copy',
    )
    if path_entries:
        emit_file_path_list_card(path_entries, cli='batch_copy')
    return EXIT_OK if is_success else EXIT_BUSINESS_ERROR
