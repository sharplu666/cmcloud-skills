#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一写操作 jsonl 日志（stdout 的 <log_path> 标记所指向的文件）。

仅指 `append_operation_log` 写入的
`workspace/dynamic_log/<YYYY-MM-DD>/{command}_{timestamp}.jsonl`，
**不是** stdout 上的 JSONL 业务结果行（record: meta / file 等）。

该文件始终记录**操作完成后**的文件身份（fileId 与元数据），而非操作前的源文件。
例如：复制写 newFileId；移动写 rstFile.fileId；重命名优先用 batchUpdate 响应中的结果 fileId。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

DEFAULT_WORKSPACE_DIR = os.getenv('OPENCLAW_WORKSPACE', '/home/node/.openclaw/workspace')
DYNAMIC_LOG_DIR_NAME = 'dynamic_log'

_operation_log_command: str | None = None
_operation_log_workspace: str | None = None
_operation_log_timestamp: str | None = None
_operation_log_date: str | None = None
_operation_log_abs_path: str | None = None
_operation_log_rel_path: str | None = None
_operation_log_has_records: bool = False


def _sanitize_command_name(command: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9_-]+', '_', str(command or '').strip())
    return text.strip('_') or 'operation'


def init_operation_log(
    command: str,
    *,
    workspace_dir: str | None = None,
) -> None:
    """登记写操作日志上下文；文件在首次 append 时按 {command}_{timestamp}.jsonl 创建。"""
    global _operation_log_command, _operation_log_workspace, _operation_log_timestamp
    global _operation_log_date
    global _operation_log_abs_path, _operation_log_rel_path, _operation_log_has_records
    _operation_log_has_records = False
    _operation_log_abs_path = None
    _operation_log_rel_path = None
    _operation_log_command = _sanitize_command_name(command)
    _operation_log_workspace = str(workspace_dir or DEFAULT_WORKSPACE_DIR).rstrip('/')
    now = datetime.now()
    _operation_log_timestamp = now.strftime('%Y%m%d%H%M%S')
    _operation_log_date = now.strftime('%Y-%m-%d')


def _ensure_operation_log_paths() -> bool:
    """首次写入时解析路径并确保 dynamic_log/<date> 目录存在（不创建空日志文件）。"""
    global _operation_log_abs_path, _operation_log_rel_path
    if not _operation_log_command or not _operation_log_timestamp or not _operation_log_date:
        return False
    if _operation_log_abs_path and _operation_log_rel_path:
        return True
    ws = _operation_log_workspace or DEFAULT_WORKSPACE_DIR
    log_dir = os.path.join(ws, DYNAMIC_LOG_DIR_NAME, _operation_log_date)
    os.makedirs(log_dir, exist_ok=True)
    filename = f'{_operation_log_command}_{_operation_log_timestamp}.jsonl'
    _operation_log_abs_path = os.path.join(log_dir, filename)
    _operation_log_rel_path = f'workspace/{DYNAMIC_LOG_DIR_NAME}/{_operation_log_date}/{filename}'
    return True


def get_operation_log_rel_path() -> str | None:
    return _operation_log_rel_path if _operation_log_has_records else None


def has_operation_log_records() -> bool:
    return _operation_log_has_records


def get_operation_log_path_for_output() -> str | None:
    """仅当已写入至少一条日志时返回相对路径，供 <log_path> 输出。"""
    if not _operation_log_has_records:
        return None
    return _operation_log_rel_path


def is_async_task_success(result: dict[str, Any]) -> bool:
    """异步任务轮询终态：status==3 为成功。"""
    data = result.get('data') or {}
    try:
        return int(data.get('status')) == 3
    except (TypeError, ValueError):
        return False


def append_operation_log(record: dict[str, Any]) -> None:
    """追加一行到 <log_path> 指向的 jsonl 文件（非 stdout JSONL）。

    目录类记录（type=folder）不写入：操作日志只记录文件，不记录目录本身。
    """
    global _operation_log_has_records
    if str(record.get('type') or '').strip() == 'folder':
        return
    if not _ensure_operation_log_paths():
        return
    with open(_operation_log_abs_path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    _operation_log_has_records = True


def _normalize_api_category(raw: str) -> str:
    """个人云 category 原始值 → 英文 token（与 cm_cloud_utils.category_render_token 一致）。"""
    s = str(raw or '').strip().lower()
    if s in ('doc', 'document', '文档', '4'):
        return 'doc'
    if s in ('image', '图片', 'img', '1'):
        return 'image'
    if s in ('audio', '音频', '2'):
        return 'audio'
    if s in ('video', '视频', '3'):
        return 'video'
    if s in ('folder', '文件夹', '5'):
        return 'folder'
    return s or 'others'


def resolve_operation_log_type(*, category: str = '', api_type: str = '') -> str:
    """根据 batchGet / CLI 返回的 category、type 解析日志 type（folder/img/video/audio/doc）。"""
    cat = _normalize_api_category(category)
    typ = str(api_type or '').strip().lower()

    if cat == 'folder' or typ == 'folder':
        return 'folder'
    if cat in ('image', 'img') or typ in ('image', 'img'):
        return 'img'
    if cat == 'video' or typ == 'video':
        return 'video'
    if cat == 'audio' or typ == 'audio':
        return 'audio'
    if cat in ('doc', 'document', 'others'):
        return 'doc'
    if typ in ('doc', 'document'):
        return 'doc'
    if typ == 'file':
        return 'doc'
    return 'doc'


def get_file_type_for_log(category: str) -> str:
    """兼容旧调用：仅传入 category 时解析日志 type。"""
    return resolve_operation_log_type(category=category)


def post_operation_file_id_from_batch_update(
    sub_response: dict[str, Any] | None,
    request_file_id: str,
) -> str:
    """batchUpdate 子响应 → <log_path> 日志用的重命名后 fileId。"""
    req = str(request_file_id or '').strip()
    if not isinstance(sub_response, dict):
        return req
    data = sub_response.get('data')
    if isinstance(data, dict):
        for key in ('fileId', 'appFileId', 'newFileId'):
            fid = str(data.get(key) or '').strip()
            if fid:
                return fid
        nested = data.get('file')
        if isinstance(nested, dict):
            fid = str(nested.get('fileId') or nested.get('appFileId') or '').strip()
            if fid:
                return fid
    return req


def post_operation_file_id_from_task_row(
    row: dict[str, Any],
    *,
    require_new_file: bool = False,
) -> str:
    """异步复制/移动结果行 → <log_path> 日志用的操作后 fileId。"""
    if str(row.get('errCode') or '') != '0000':
        return ''
    old_id = str(row.get('oldFileId') or row.get('fileId') or '').strip()
    new_id = str(row.get('newFileId') or '').strip()
    if not new_id:
        return ''
    if require_new_file and new_id == old_id:
        return ''
    return new_id


def build_operation_log_record(
    *,
    file_id: str,
    file_name: str,
    file_extension: str = '',
    record_type: str = '',
    category: str = '',
    api_type: str = '',
    in_folder: bool | None = None,
    parent_file_id: str = '',
    parent_file_name: str = '',
    # 兼容 AI utils 旧参数名
    file_type: str = '',
) -> dict[str, Any]:
    """构造单行操作日志。

    inFolder 仅整理 CLI 为 true（须带 parentFileId、parentFileName）；移动 / 复制 / 转存 CLI 为 false。
    整理 CLI 不记录新建目录，<log_path> 仅含成功归入目录的文件行。
    """
    log_type = (
        str(record_type or file_type or '').strip()
        or resolve_operation_log_type(category=category, api_type=api_type)
    )
    record: dict[str, Any] = {
        'fileId': file_id,
        'fileName': file_name,
        'fileExtension': file_extension or '',
        'type': log_type,
    }
    if in_folder is not None:
        record['inFolder'] = in_folder
        if in_folder:
            record['parentFileId'] = parent_file_id
            record['parentFileName'] = parent_file_name
    return record


def log_record_from_file_info(info: dict[str, Any]) -> dict[str, Any]:
    """fileInfoList / batchGet 字典 → 操作日志行（不含 inFolder）。"""
    return build_operation_log_record(
        file_id=str(info.get('fileId') or ''),
        file_name=str(info.get('name') or info.get('fileName') or ''),
        file_extension=str(info.get('fileExtension') or ''),
        category=str(info.get('category') or ''),
        api_type=str(info.get('type') or ''),
    )


def enriched_row_to_operation_log_record(
    row: dict[str, Any],
    *,
    in_folder: bool | None = None,
    parent_file_id: str = '',
    parent_file_name: str = '',
) -> dict[str, Any]:
    """富化行 → 写操作日志。"""
    return build_operation_log_record(
        file_id=str(row.get('fileId') or ''),
        file_name=str(row.get('name') or ''),
        file_extension=str(row.get('fileExtension') or ''),
        category=str(row.get('category') or ''),
        api_type=str(row.get('type') or ''),
        in_folder=in_folder,
        parent_file_id=parent_file_id,
        parent_file_name=parent_file_name,
    )


def append_ai_moved_result_logs(
    result_file_infos: dict[str, dict[str, Any]],
    move_result: dict[str, Any],
) -> None:
    """AI 技能：结果文件移入 AI 空间后，每条结果写一行日志（无 inFolder）。"""
    for moved in move_result.get('movedFiles') or []:
        if not isinstance(moved, dict):
            continue
        fid = str(moved.get('fileId') or '').strip()
        if not fid:
            continue
        orig = dict(result_file_infos.get(fid) or {})
        name_path = str(moved.get('namePath') or '').strip()
        if name_path:
            base = os.path.basename(name_path)
            if base:
                orig['name'] = base
        orig['fileId'] = fid
        append_operation_log(log_record_from_file_info(orig))
