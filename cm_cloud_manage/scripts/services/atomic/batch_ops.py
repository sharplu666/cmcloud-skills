#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量复制/移动/重命名业务编排（异步任务轮询）。"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict

from utils.config import BATCH_FOLDER_CHILDREN_PAGE_SIZE
from mclaw.shared.cm_cloud.personal_task import PersonalTaskPollError, poll_personal_task
from mclaw.utils.settings import async_task_wait_for_action
from operation_log import append_operation_log, enriched_row_to_operation_log_record
from services.atomic.client import (
    api_batch_copy_async,
    api_batch_move_async,
    api_search_merge_file,
    api_task_get,
    build_search_file_param_v3,
)
from mclaw.shared.cm_cloud.file_enrichment import get_enriched_files_by_ids
from mclaw.shared.postprocess.merge_normalize import split_result_rows
from session_folder import ensure_default_session_upload_parent


def _poll_batch_task(
    task_id: str,
    *,
    action: str,
    command: str,
) -> Dict[str, Any]:
    interval_sec, timeout_sec = async_task_wait_for_action(action)
    try:
        data = poll_personal_task(
            task_id,
            get_fn=api_task_get,
            interval_sec=interval_sec,
            timeout_sec=timeout_sec,
        )
    except PersonalTaskPollError as exc:
        raise RuntimeError(f'{command}失败：{exc}') from exc
    return data


def batch_copy_to_parent_file_id(
    file_ids: list,
    target_parent_file_id: str,
    *,
    command: str = 'batch_copy',
) -> list:
    normalized_file_ids = [str(fid or '').strip() for fid in file_ids if str(fid or '').strip()]
    if not normalized_file_ids:
        raise ValueError('批量复制失败：file_ids 不能为空')
    normalized_parent_file_id = str(target_parent_file_id or '').strip()
    if not normalized_parent_file_id:
        raise ValueError('批量复制失败：target_parent_file_id 不能为空')

    task_id = api_batch_copy_async(normalized_file_ids, normalized_parent_file_id)
    data = _poll_batch_task(task_id, action='batch_copy', command=command)
    copied_rows = [
        {
            'errCode': row.get('errCode'),
            'message': row.get('message'),
            'oldFileId': (row.get('srcFile') or {}).get('fileId'),
            'fileId': (row.get('srcFile') or {}).get('fileId'),
            'newFileId': (row.get('rstFile') or {}).get('fileId'),
        }
        for row in (data.get('batchFileResults') or [])
    ]

    copied_row_queues: Dict[str, deque] = {}
    for row in copied_rows:
        old_file_id = str(row.get('oldFileId') or row.get('fileId') or '').strip()
        copied_row_queues.setdefault(old_file_id, deque()).append(row)

    rows = []
    for file_id in normalized_file_ids:
        row_queue = copied_row_queues.get(file_id)
        if row_queue:
            rows.append(row_queue.popleft())
        else:
            rows.append({
                'errCode': '9999',
                'message': '批量复制结果缺失',
                'oldFileId': file_id,
                'fileId': file_id,
                'newFileId': '',
            })

    return rows

def batch_move_to_parent_file_id(
    file_ids: list,
    target_parent_file_id: str,
    *,
    command: str = 'batch_move',
) -> list:
    normalized_file_ids = [str(fid or '').strip() for fid in file_ids if str(fid or '').strip()]
    if not normalized_file_ids:
        raise ValueError('批量移动失败：file_ids 不能为空')
    normalized_parent_file_id = str(target_parent_file_id or '').strip()
    if not normalized_parent_file_id:
        raise ValueError('批量移动失败：target_parent_file_id 不能为空')

    task_id = api_batch_move_async(normalized_file_ids, normalized_parent_file_id)
    data = _poll_batch_task(task_id, action='batch_move', command=command)
    moved_rows = [
        {
            'errCode': row.get('errCode'),
            'message': row.get('message'),
            'oldFileId': (row.get('srcFile') or {}).get('fileId'),
            'fileId': (row.get('srcFile') or {}).get('fileId'),
            'newFileId': (row.get('rstFile') or {}).get('fileId') or (row.get('srcFile') or {}).get('fileId'),
        }
        for row in (data.get('batchFileResults') or [])
    ]

    moved_row_queues: Dict[str, deque] = {}
    for row in moved_rows:
        old_file_id = str(row.get('oldFileId') or row.get('fileId') or '').strip()
        moved_row_queues.setdefault(old_file_id, deque()).append(row)

    rows = []
    for file_id in normalized_file_ids:
        row_queue = moved_row_queues.get(file_id)
        if row_queue:
            rows.append(row_queue.popleft())
        else:
            rows.append({
                'errCode': '9999',
                'message': '批量移动结果缺失',
                'oldFileId': file_id,
                'fileId': file_id,
                'newFileId': '',
            })

    return rows

def _copy_into_ai_space(
    copy_file_ids: list[str],
    *,
    raw_session_id: str,
    command: str,
    messages: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """复制 copy_file_ids 到会话默认目录，返回 (oldFileId→newFileId 成功映射, oldFileId→失败原因)。

    messages 提供四类失败文案键：'exc'/'failed' 为带 {detail} 占位的模板，
    'missing'（返回成功行但无新 fileId）与 'empty'（复制返回空且未抛异常）为固定文案。
    """
    try:
        folder_id, _target_path = ensure_default_session_upload_parent(
            raw_session_id, error_cls=RuntimeError
        )
        rows = batch_copy_to_parent_file_id(copy_file_ids, folder_id, command=command)
    except (RuntimeError, ValueError) as e:
        return {}, {fid: messages['exc'].format(detail=e) for fid in copy_file_ids}

    if not rows:
        return {}, {fid: messages['empty'] for fid in copy_file_ids}

    ok_rows, failed_rows = split_result_rows(rows)
    failures: dict[str, str] = {}
    for row in failed_rows:
        fid = str(row.get('oldFileId') or row.get('fileId') or '').strip()
        detail = str(row.get('message') or row.get('errCode') or '未知错误').strip()
        failures[fid] = messages['failed'].format(detail=detail)
    id_map = {
        str(row.get('oldFileId') or row.get('fileId') or '').strip(): str(row.get('newFileId') or '').strip()
        for row in ok_rows
        if str(row.get('oldFileId') or row.get('fileId') or '').strip() and str(row.get('newFileId') or '').strip()
    }
    for fid in copy_file_ids:
        if fid not in failures and fid not in id_map:
            failures[fid] = messages['missing']
    return id_map, failures

def _append_folder_children_logs(
    ok_fids: set[str],
    post_rename_id_map: dict[str, str],
    log_enriched_by_id: dict[str, dict[str, Any]],
) -> None:
    """重命名文件夹后，将文件夹内所有子文件写入 <log_path> 操作日志。"""
    for fid in ok_fids:
        post_fid = post_rename_id_map.get(fid, fid)
        info = log_enriched_by_id.get(post_fid, {})
        cat = str(info.get('category') or '').strip().lower()
        typ = str(info.get('type') or '').strip().lower()
        if cat != 'folder' and typ not in ('folder', '2'):
            continue

        folder_name = str(info.get('name') or '')
        try:
            param = build_search_file_param_v3(
                include_file_id_list=[post_fid],
                recursion=True,
            )
            children, _, _, _ = api_search_merge_file(
                param,
                page_size=BATCH_FOLDER_CHILDREN_PAGE_SIZE,
                sort_infos=[{'orderBy': 'relevancy', 'orderDirection': True}],
            )
        except RuntimeError:
            continue

        child_ids = [
            str(c.get('fileId') or '').strip()
            for c in children
            if str(c.get('fileId') or '').strip() and str(c.get('fileId') or '').strip() != post_fid
        ]
        if not child_ids:
            continue

        try:
            enriched = get_enriched_files_by_ids(child_ids, verbose=False)
        except RuntimeError:
            continue

        for child in enriched:
            append_operation_log(
                enriched_row_to_operation_log_record(
                    child,
                    in_folder=True,
                    parent_file_id=post_fid,
                    parent_file_name=folder_name,
                )
            )
