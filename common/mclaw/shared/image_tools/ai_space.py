#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 空间文件归档业务编排（shared 层）。

仅承载业务编排逻辑（会话目录解析、结果子目录创建、移动结果文件、查询移动后路径），
**不发 HTTP、不持鉴权/host**。所有 HTTP 调用通过调用方注入的
``dispatcher: ApiDispatcher`` 以属性链方式完成：

    dispatcher.operation.batch_move_files(req)         # 批量移动
    dispatcher.personal_saas.get_path(req)              # 查询全路径

调用方负责构造 dispatcher（``ApiDispatcher(host=HOST, auth_fn=get_auth_header)``）。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Any, Tuple

from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas.get_path_api import GetPathRequest
from mclaw.api.operation.batch_move_files_api import BatchMoveFilesRequest

try:
    from cli_timing import write_cli_output_line
except ImportError:
    def write_cli_output_line(line: str) -> None:
        print(line, flush=True)

# 会话目录解析（非 HTTP 调用，属会话编排逻辑，与本层定位不冲突）
from session_folder import (
    ensure_default_session_upload_parent,
    ensure_task_named_session_folder,
)
# session 读取 + normalize（与 cm_cloud_organize/async_submit/submit.py 同款）
from mclaw.shared.cm_cloud.session_cli_validate import (
    extract_session_id,
    parse_cli_session_raw,
    parse_cron_job_id,
    resolve_current_session,
)


__all__ = [
    'move_result_to_ai_space',
    'move_result_to_directory',
    'resolve_session_from_env',
    'ensure_session_default_dir',
    'ensure_session_query_dir',
]


def move_result_to_ai_space(
    session_id: str,
    file_ids: List[str],
    dispatcher: ApiDispatcher,
) -> Dict[str, Any]:
    """将结果文件移动到会话对应的 AI 空间目录（移动，原位置删除）。

    目标目录通过 ``session_folder.ensure_default_session_upload_parent`` 解析
    （服务端优先 + 本地兜底），返回的 ``(folderId, full_path)`` 直接作为移动目标。

    移动失败时不会抛出异常，而是返回 ``status="error"`` 和空的 ``movedFiles``，
    确保调用方的结果输出逻辑不被阻断。

    Args:
        session_id: MClaw session id（如 ``agent:main:...``）。
        file_ids: 要移动的文件 ID 列表。
        dispatcher: 调用方注入的 ``ApiDispatcher`` 实例。本函数通过属性链调用
            ``dispatcher.operation.batch_move_files`` 与 ``dispatcher.personal_saas.get_path``。

    Returns:
        ``{"status": "success"|"error", "targetPath": str, "taskId": str,
           "movedFiles": [{"fileId": str, "namePath": str}], "message": str}``
    """
    if not file_ids:
        raise ValueError('file_ids 不能为空')

    target_path = ''  # 异常分支引用兜底
    try:
        # 通过 session_folder.py 统一解析会话目标目录（服务端优先 + 本地兜底）
        dir_id, target_path = ensure_default_session_upload_parent(session_id)

        # 批量移动：dispatcher 属性链调用，内置轮询到终态
        req = BatchMoveFilesRequest(
            file_ids=list(file_ids),
            to_parent_file_id=dir_id,
            poll_interval=5.0,
            poll_max_attempts=720,  # 3600s / 5s = 720 次，对齐旧 _TASK_POLL_TIMEOUT
        )
        poll_resp = dispatcher.operation.batch_move_files(req)

        # 从 batch_file_results 中提取移动成功的 fileId，查询新路径
        moved_file_ids: List[str] = []
        for row in (poll_resp.batch_file_results or []):
            src = row.get('srcFile') if isinstance(row, dict) else None
            fid = (src or {}).get('fileId')
            if fid and str(row.get('errCode') or '0000') == '0000':
                moved_file_ids.append(fid)

        path_map: Dict[str, str] = {}
        if moved_file_ids:
            path_resp = dispatcher.personal_saas.get_path(
                GetPathRequest(file_ids=moved_file_ids)
            )
            path_map = {it.file_id: it.name_path for it in path_resp.ok_items}

        moved_files = [
            {
                'fileId': fid,
                'namePath': os.path.join(
                    target_path,
                    os.path.basename(path_map.get(fid, '')),
                ),
            }
            for fid in moved_file_ids
        ]

        return {
            'status': 'success',
            'targetPath': target_path,
            'targetDirFileId': dir_id,
            'taskId': poll_resp.task_id,
            'movedFiles': moved_files,
            'message': f'已移动 {len(moved_file_ids)} 个文件到 {target_path}',
        }
    except Exception as exc:
        write_cli_output_line(f'移动结果文件到 AI 空间失败: {exc}')
        return {
            'status': 'error',
            'targetPath': target_path,
            'targetDirFileId': '',
            'taskId': '',
            'movedFiles': [],
            'message': f'移动失败: {exc}',
        }


def _parse_id_path_segments(id_path: str) -> List[str]:
    """将 ``idPath``（如 ``root:/111/222/333``）解析为 fileId 分段列表。"""
    text = str(id_path or '').strip()
    if not text:
        return []
    if ':' in text:
        text = text.split(':', 1)[1]
    return [seg for seg in text.strip('/').split('/') if seg]


def _parent_file_id_from_id_path(id_path: str) -> str:
    """从 ``idPath`` 取父目录 fileId；顶层项返回 ``'/'``。"""
    segments = _parse_id_path_segments(id_path)
    if len(segments) < 2:
        return '/'
    return segments[-2]


def _is_id_path_strict_ancestor(ancestor_id: str, id_path: str) -> bool:
    """``ancestor_id`` 是否为 ``id_path`` 所表节点的严格祖先（不含自身）。"""
    if not ancestor_id or not id_path:
        return False
    segments = _parse_id_path_segments(id_path)
    if not segments:
        return False
    try:
        idx = segments.index(ancestor_id)
    except ValueError:
        return False
    return idx < len(segments) - 1


def _classify_move_target(
    file_id: str,
    to_parent_file_id: str,
    *,
    file_id_path: str = '',
    file_type: str = '',
    target_id_path: str = '',
) -> str:
    """判定单个文件是否可移动到 ``to_parent_file_id``。

    Returns:
        ``movable``：可移动；``already_there``：已在目标目录（无需调用移动接口）；
        ``invalid``：不可移动（自身或自身子目录）。
    """
    if to_parent_file_id == file_id:
        return 'invalid'

    if file_id_path and to_parent_file_id == _parent_file_id_from_id_path(file_id_path):
        return 'already_there'

    if file_type == 'folder' and target_id_path and _is_id_path_strict_ancestor(file_id, target_id_path):
        return 'invalid'

    return 'movable'


def _partition_movable_file_ids(
    file_ids: List[str],
    to_parent_file_id: str,
    path_map: Dict[str, Dict[str, str]],
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """按移动合法性拆分待移动 fileId。

    Returns:
        ``(movable, already_there, invalid, unknown)``。
        ``unknown`` 为未能查到路径、无法本地判定的 id（仍交给移动接口处理）。
    """
    target_info = path_map.get(to_parent_file_id) or {}
    target_id_path = target_info.get('id_path', '')

    movable: List[str] = []
    already_there: List[str] = []
    invalid: List[str] = []
    unknown: List[str] = []

    for fid in file_ids:
        info = path_map.get(fid)
        if not info:
            unknown.append(fid)
            continue
        verdict = _classify_move_target(
            fid,
            to_parent_file_id,
            file_id_path=info.get('id_path', ''),
            file_type=info.get('type', ''),
            target_id_path=target_id_path,
        )
        if verdict == 'movable':
            movable.append(fid)
        elif verdict == 'already_there':
            already_there.append(fid)
        else:
            invalid.append(fid)

    return movable, already_there, invalid, unknown


def _build_path_info_map(items: List[Any]) -> Dict[str, Dict[str, str]]:
    """将 ``get_path`` 的 ``ok_items`` 转为 ``fileId -> {id_path, type, name_path}``。"""
    out: Dict[str, Dict[str, str]] = {}
    for it in items:
        fid = str(getattr(it, 'file_id', '') or '').strip()
        if not fid:
            continue
        out[fid] = {
            'id_path': str(getattr(it, 'id_path', '') or ''),
            'type': str(getattr(it, 'type', '') or ''),
            'name_path': str(getattr(it, 'name_path', '') or ''),
        }
    return out


def move_result_to_directory(
    file_ids: List[str],
    to_parent_file_id: str,
    dispatcher: ApiDispatcher,
) -> Dict[str, Any]:
    """将结果文件移动到**调用方指定的目录**（按 fileId），返回目录路径回执所需信息。

    与 :func:`move_result_to_ai_space` 的差异：目标目录由调用方直接给定 fileId
    （通常来自「云盘文件管理」的搜索结果），而非从 session 解析 AI 空间默认目录。
    用于 image_tool 各能力支持 ``--save-dir-id`` 另存到用户指定目录——目录的路径/合法性
    解析仍由云盘文件管理技能负责，本函数只收 fileId 并执行移动。

    移动前通过 ``get_path`` 的 ``idPath`` 预检：跳过已在目标目录的文件；
    剔除无法移动到自身或自身子目录的 fileId（对齐 ``04010317 FILE_MOVE_IN_SITU``）。

    移动失败时不抛异常，返回 ``status="error"`` 与空的 ``movedFiles``，
    确保调用方的结果输出逻辑不被阻断（与 move_result_to_ai_space 一致）。

    Args:
        file_ids: 要移动的文件 ID 列表。
        to_parent_file_id: 目标目录 fileId（由调用方解析，本函数不做路径校验）。
        dispatcher: 调用方注入的 ``ApiDispatcher``。本函数通过属性链调用
            ``dispatcher.operation.batch_move_files`` 与 ``dispatcher.personal_saas.get_path``。

    Returns:
        ``{"status": "success"|"error", "targetPath": str, "targetDirFileId": str,
           "taskId": str, "movedFiles": [{"fileId": str, "namePath": str}], "message": str}``。
        ``targetPath`` 为目标目录的 namePath，可直接用作 ``:::filePathList`` 的 ``filePath``。
    """
    if not file_ids:
        raise ValueError('file_ids 不能为空')
    if not to_parent_file_id:
        raise ValueError('to_parent_file_id 不能为空')

    target_dir_file_id = to_parent_file_id
    target_path = ''  # 异常分支引用兜底
    try:
        lookup_ids = list(dict.fromkeys([*file_ids, target_dir_file_id]))
        path_resp = dispatcher.personal_saas.get_path(GetPathRequest(file_ids=lookup_ids))
        path_info_map = _build_path_info_map(path_resp.ok_items)
        target_path = (path_info_map.get(target_dir_file_id) or {}).get('name_path', '')

        movable_ids, already_there_ids, invalid_ids, unknown_ids = _partition_movable_file_ids(
            list(file_ids),
            target_dir_file_id,
            path_info_map,
        )
        ids_to_move = movable_ids + unknown_ids

        if invalid_ids and not ids_to_move and not already_there_ids:
            return {
                'status': 'error',
                'targetPath': target_path,
                'targetDirFileId': target_dir_file_id,
                'taskId': '',
                'movedFiles': [],
                'message': (
                    f'移动失败：{len(invalid_ids)} 个文件无法移动到自身或自身子目录下'
                    f'（fileId={", ".join(invalid_ids)}）'
                ),
            }

        moved_file_ids: List[str] = []
        task_id = ''
        if ids_to_move:
            req = BatchMoveFilesRequest(
                file_ids=list(ids_to_move),
                to_parent_file_id=target_dir_file_id,
                poll_interval=5.0,
                poll_max_attempts=720,  # 3600s / 5s = 720 次，对齐 move_result_to_ai_space
            )
            poll_resp = dispatcher.operation.batch_move_files(req)
            task_id = poll_resp.task_id
            for row in (poll_resp.batch_file_results or []):
                src = row.get('srcFile') if isinstance(row, dict) else None
                fid = (src or {}).get('fileId')
                if fid and str(row.get('errCode') or '0000') == '0000':
                    moved_file_ids.append(fid)

            refresh_ids = [
                fid for fid in moved_file_ids
                if fid not in path_info_map or not path_info_map[fid].get('name_path')
            ]
            if refresh_ids:
                refresh_resp = dispatcher.personal_saas.get_path(
                    GetPathRequest(file_ids=refresh_ids)
                )
                path_info_map.update(_build_path_info_map(refresh_resp.ok_items))

        result_file_ids = list(dict.fromkeys([*moved_file_ids, *already_there_ids]))
        moved_files = [
            {
                'fileId': fid,
                'namePath': (path_info_map.get(fid) or {}).get('name_path', ''),
            }
            for fid in result_file_ids
        ]

        message_parts: List[str] = []
        if moved_file_ids:
            message_parts.append(
                f'已移动 {len(moved_file_ids)} 个文件到 {target_path or target_dir_file_id}'
            )
        if already_there_ids:
            message_parts.append(f'{len(already_there_ids)} 个文件已在目标目录，无需移动')
        if invalid_ids:
            message_parts.append(
                f'跳过 {len(invalid_ids)} 个无法移动的文件（无法移动到自身或自身子目录）'
            )
        if not message_parts:
            message_parts.append(f'未移动任何文件到 {target_path or target_dir_file_id}')

        return {
            'status': 'success' if result_file_ids or not invalid_ids else 'error',
            'targetPath': target_path,
            'targetDirFileId': target_dir_file_id,
            'taskId': task_id,
            'movedFiles': moved_files,
            'message': '；'.join(message_parts),
        }
    except Exception as exc:
        write_cli_output_line(f'移动结果文件到指定目录失败: {exc}')
        return {
            'status': 'error',
            'targetPath': target_path,
            'targetDirFileId': target_dir_file_id,
            'taskId': '',
            'movedFiles': [],
            'message': f'移动失败: {exc}',
        }


def resolve_session_from_env(
    *,
    required: bool = True,
    error_cls: type[Exception] = ValueError,
) -> tuple[str, str]:
    """从环境变量 ``MCLAW_CURRENT_SESSION`` 读取并 normalize 会话。

    与 ``cm_cloud_organize/scripts/async_submit/submit.py`` 同款 normalize：
      - 普通对话 ``agent:main:xxx`` / ``main:xxx`` → ``xxx``
      - 定时任务 ``agent:main:cron:<jobId>:run:<runId>`` → ``<jobId>``（切 ``:run:`` 后缀）
      - 聚合定时任务 → ``share_cron_<shareId>`` token

    供各 image_tool 技能复用：不再从 CLI 收 session，统一由环境变量获取。

    Args:
        required: 环境变量缺失时是否抛错；``False`` 时缺失返回 ``('', '')``。
        error_cls: ``required=True`` 且缺失/非法时抛出的异常类型。

    Returns:
        ``(raw_session, session_id)``：``raw_session`` 原样，供
        :func:`ensure_session_default_dir` 等**需 raw 入参**的接口；
        ``session_id`` 为 normalize 后的标识，便于日志/透传。``required=False`` 且缺失时为 ``('', '')``。
    """
    raw_session = resolve_current_session(required=required, error_cls=error_cls)
    if not raw_session:
        return '', ''
    session_id = extract_session_id(raw_session)
    parsed = parse_cli_session_raw(raw_session)
    if parsed.kind == 'cron':
        session_id = parse_cron_job_id(parsed.body)
    return raw_session, session_id


def ensure_session_default_dir(
    raw_session: str,
    *,
    verbose: bool = False,
) -> tuple[str, str]:
    """按会话**创建**（ensure，非仅查看）默认保存目录，返回 ``(fileId, fullPath)``。

    包装 ``session_folder.ensure_default_session_upload_parent``（``create=True``：服务端
    ``/session/folder/name`` + ``enableAutoCreateDir=true`` 真实建目录，失败本地逐级兜底）。
    入参须为 **raw** session（``agent:main:xxx``），由 :func:`resolve_session_from_env` 返回的
    ``raw_session`` 直接传入即可。

    创建失败时**不抛异常**，打印告警并返回 ``("", "")``，由调用方决定是否跳过归档
   （与 :func:`move_result_to_ai_space` 的吞错降级精神一致）。

    Args:
        raw_session: raw 会话串（``agent:main:xxx``）。
        verbose: 透传给 ``ensure_default_session_upload_parent`` 的详细日志开关。

    Returns:
        ``(folderId, fullPath)``；失败为 ``("", "")``。
    """
    try:
        dir_id, full_path = ensure_default_session_upload_parent(raw_session, verbose=verbose)
        write_cli_output_line(f'默认保存目录就绪: {full_path or dir_id}')
        return dir_id, full_path
    except Exception as exc:
        write_cli_output_line(f'创建默认保存目录失败: {exc}')
        return '', ''


# ──────────────────────────── 结果保存目录（按 query 命名） ────────────────────────────

# query 目录名最大长度（清洗后截断）
QUERY_DIR_NAME_MAX_LEN = 50


def _sanitize_query_dir_name(dir_name: str) -> str:
    """清洗 query 目录名：去路径分隔符与控制字符、压缩连续空白、截断到 50 字符。"""
    name = re.sub(r'[/\\\x00-\x1f]', '', str(dir_name or ''))
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > QUERY_DIR_NAME_MAX_LEN:
        name = name[:QUERY_DIR_NAME_MAX_LEN].rstrip(' .')
    return name


def ensure_session_query_dir(
    raw_session: str,
    dir_name: str,
    *,
    verbose: bool = False,
) -> tuple[str, str]:
    """按 query **创建**（ensure，非仅查看）结果保存目录，返回 ``(fileId, fullPath)``。

    目录直接挂在会话子目录（``对话文件`` / cron 场景 ``我的任务``）下，以 query 命名：
    ``/AI空间/<APP>/<对话文件|我的任务>/<query>``。不经过服务端按会话生成的一级目录——
    服务端目录名取自会话内容，与 query 嵌套会产生重复或误导（如
    ``对话文件/抠出图中的人物/抠出图中的人物``）。

    名称先经 :func:`_sanitize_query_dir_name` 清洗；同名目录已存在时复用（ensure 语义）。
    创建失败时**不抛异常**，打印告警并返回 ``("", "")``，由调用方回退
    （如回退 :func:`ensure_session_default_dir` 或跳过归档）。

    Args:
        raw_session: raw 会话串（``agent:main:xxx``）。
        dir_name: 目录名（原始 query，本函数内部清洗）。
        verbose: 透传给底层建目录逻辑的详细日志开关。

    Returns:
        ``(folderId, fullPath)``；失败或名称清洗后为空为 ``("", "")``。
    """
    name = _sanitize_query_dir_name(dir_name)
    if not name:
        return '', ''
    try:
        dir_id, full_path = ensure_task_named_session_folder(raw_session, name, verbose=verbose)
        write_cli_output_line(f'结果保存目录就绪: {full_path or dir_id}')
        return dir_id, full_path
    except Exception as exc:
        write_cli_output_line(f'创建结果保存目录失败: {exc}')
        return '', ''
