#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：batch_move"""
from __future__ import annotations

from cli.cli_runtime import (
    Any,
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    MCLAW_ALLOWED_DIR,
    MOVE_SKIP_OUTSIDE_MCLAW_PREFIX,
    append_operation_log,
    batch_is_under_ai_space,
    collect_deduped_file_path_entries,
    collect_success_result_file_ids,
    deque,
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
    resolve_current_session,
    snapshot_trace_id,
)
from services.atomic.batch_ops import batch_move_to_parent_file_id

def move_skip_outside_mclaw_message() -> str:
    return (
        f'{MOVE_SKIP_OUTSIDE_MCLAW_PREFIX}。'
        '源文件在 MClaw 空间外时不能移动；若需保留原文件并落到目标目录，'
        '请向用户说明后改用 batch_copy（file_ids、to_parent_file_id、session 与本次移动相同）。'
    )

def build_batch_copy_suggested_action(
    file_ids: list[str],
    to_parent_file_id: str,
    session: str = '',
) -> str:
    # session 参数兼容保留；建议命令中的 session 占位取自环境变量（缺省用占位符满足位置参数）
    _ = session
    ids = ','.join(str(fid).strip() for fid in file_ids if str(fid).strip())
    sess = resolve_current_session(required=False) or 'ignored'
    return f'batch_copy {ids} {to_parent_file_id} {sess}'.strip()


def run(
    file_ids: list,
    to_parent_file_id: str,
    session: str = '',
) -> int:
    # 位置参数 session 仅兼容保留（suggestedAction 读 MCLAW_CURRENT_SESSION）
    _ = session
    try:
        normalized_file_ids = [str(fid or '').strip() for fid in file_ids if str(fid or '').strip()]
        if not normalized_file_ids:
            exit_with_error('批量移动失败：file_ids 不能为空', code=EXIT_INPUT_ERROR)

        normalized_target_parent_file_id = str(to_parent_file_id or '').strip()
        if not normalized_target_parent_file_id:
            exit_with_error('批量移动失败：to_parent_file_id 不能为空', code=EXIT_INPUT_ERROR)

        target_info = get_single_file_info(normalized_target_parent_file_id, action='移动文件')
        target_type = str(target_info.get('type') or '').strip().lower()
        target_category = str(target_info.get('category') or '').strip().lower()
        if target_type not in ('folder', '2') and target_category != 'folder':
            exit_with_error(
                f'批量移动失败：to_parent_file_id={normalized_target_parent_file_id} 不是文件夹',
                code=EXIT_INPUT_ERROR,
                from_api=False,
            )

        if not is_under_ai_space(normalized_target_parent_file_id):
            exit_with_error(
                f'批量移动失败：本技能仅允许在「{MCLAW_ALLOWED_DIR}」内移动，'
                f'无法在云盘其它位置执行移动（to_parent_file_id: {normalized_target_parent_file_id}）。'
                f'请将目标目录改为该空间内的文件夹 fileId；'
                f'若源文件在该空间外、仅需复制到目标目录，可改用 batch_copy。',
                code=EXIT_INPUT_ERROR,
                from_api=False,
            )

        target_path = get_single_file_path(normalized_target_parent_file_id, action='移动文件')
        ai_space_status_map = batch_is_under_ai_space(normalized_file_ids)
        movable_file_ids = [fid for fid in normalized_file_ids if ai_space_status_map.get(fid, False)]
        skipped_file_ids = [fid for fid in normalized_file_ids if not ai_space_status_map.get(fid, False)]

        moved_rows_by_file_id: dict[str, deque] = {}
        if movable_file_ids:
            moved_rows = batch_move_to_parent_file_id(
                movable_file_ids,
                normalized_target_parent_file_id,
                command='batch_move.move_files',
            )
            if not moved_rows:
                exit_with_error('批量移动失败：移动待移动文件到目标目录失败')
            for row in moved_rows:
                old_file_id = str(row.get('oldFileId') or row.get('fileId') or '').strip()
                moved_rows_by_file_id.setdefault(old_file_id, deque()).append(row)

        rows = []
        for fid in normalized_file_ids:
            if not ai_space_status_map.get(fid, False):
                rows.append({
                    'errCode': 'SKIPPED',
                    'message': move_skip_outside_mclaw_message(),
                    'oldFileId': fid,
                    'fileId': fid,
                    'newFileId': '',
                })
                continue

            row_queue = moved_rows_by_file_id.get(fid)
            if row_queue:
                rows.append(row_queue.popleft())
            else:
                rows.append({
                    'errCode': '9999',
                    'message': '批量移动结果缺失',
                    'oldFileId': fid,
                    'fileId': fid,
                    'newFileId': '',
                })
    except (RuntimeError, ValueError) as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR, from_api=True)

    snapshot_trace_id()

    ok_count = sum(1 for row in rows if str(row.get('errCode') or '') == '0000')
    skipped_count = sum(1 for row in rows if str(row.get('errCode') or '') == 'SKIPPED')
    fail_count = len(rows) - ok_count - skipped_count
    is_success = fail_count == 0 and skipped_count == 0
    status = 'success' if is_success else ('error' if ok_count == 0 else 'warning')
    if is_success:
        message = '批量移动成功'
    elif ok_count == 0 and fail_count == 0:
        message = (
            f'批量移动失败：{skipped_count} 个文件不在「{MCLAW_ALLOWED_DIR}」内，无移动权限。'
            '请向用户说明后改用 batch_copy 复制到目标目录。'
        )
    else:
        message = '批量移动失败' if ok_count == 0 else '批量移动部分成功'
        if skipped_count:
            message += (
                f'；{skipped_count} 个文件无移动权限已跳过，'
                '可改用 batch_copy 复制到同一目标目录'
            )
    moved_file_ids = [
        str(row.get('newFileId') or '').strip()
        for row in rows
        if str(row.get('errCode') or '') == '0000' and str(row.get('newFileId') or '').strip()
    ]
    enriched = get_enriched_files_by_ids(moved_file_ids)
    by_id = {str(r.get('fileId') or '').strip(): r for r in enriched}
    ordered = [by_id[fid] for fid in moved_file_ids if fid in by_id]

    # 显式写入操作日志：直接用 batchGet 富化结果
    parent_folder_name = os.path.basename(target_path.rstrip('/')) or target_path
    for fid in moved_file_ids:
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

    # 移动场景固定用文件列表 + 路径卡片，不按类型拆 image/audio/video 卡片
    meta_payload: dict[str, Any] = {
        'record': 'meta',
        'status': status,
        'command': 'batch_move',
        'message': message,
        'targetFolderFileId': normalized_target_parent_file_id,
        'targetFolderPath': target_path,
        'okCount': ok_count,
        'failCount': fail_count,
    }
    if path_entries:
        meta_payload['filePathList'] = path_entries
    if skipped_count:
        meta_payload['skippedCount'] = skipped_count
        meta_payload['skippedFileIds'] = skipped_file_ids
        meta_payload['skippedReason'] = 'source_outside_mclaw_space'
        meta_payload['suggestedAction'] = build_batch_copy_suggested_action(
            skipped_file_ids,
            normalized_target_parent_file_id,
            session,
        )
        meta_payload['hint'] = (
            f'共 {skipped_count} 个源文件不在「{MCLAW_ALLOWED_DIR}」内，无法移动。'
            '若用户需要保留原文件并落到目标目录，请说明无移动权限后执行 suggestedAction 中的 batch_copy。'
        )
    emit_jsonl(meta_payload)

    for skip_idx, fid in enumerate(skipped_file_ids, start=1):
        emit_jsonl({
            'record': 'hint',
            'index': skip_idx,
            'command': 'batch_move',
            'status': 'skipped',
            'fileId': fid,
            'message': move_skip_outside_mclaw_message(),
            'suggestedAction': build_batch_copy_suggested_action(
                [fid],
                normalized_target_parent_file_id,
                session,
            ),
        })

    emit_move_copy_write_records(
        ordered,
        operation_log_file_ids=set(
            collect_success_result_file_ids(rows, require_new_file=False)
        ),
        parent_file_id=normalized_target_parent_file_id,
        parent_file_name=os.path.basename(target_path.rstrip('/')) or target_path,
        cli='batch_move',
    )
    if path_entries:
        emit_file_path_list_card(path_entries, cli='batch_move')
    return EXIT_OK if is_success else EXIT_BUSINESS_ERROR
