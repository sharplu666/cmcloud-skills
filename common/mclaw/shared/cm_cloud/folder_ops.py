#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云目录创建与 fileId→路径映射（``cm_cloud`` 编排，非纯后处理）。

会发 HTTP（batchCheckExists / createFolder / batchGetPath），
鉴权经 ``cloud_auth``，**不**依赖 manage ``services.client``。

用法::

    from mclaw.shared.cm_cloud.folder_ops import (
        ensure_mclaw_dir_path,
        ensure_folder_path_parts,
        get_file_path_map,
    )

    folder = ensure_mclaw_dir_path('/AI空间/App/相册/2024')
    paths = get_file_path_map(['fileId1', 'fileId2'])
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Iterator, Optional, TypeVar

from mclaw.api.personal_saas._models import SubRequest, SubRequestEnvelope
from mclaw.api.personal_saas.create_folder_api import CreateFolderRequest
from mclaw.api.personal_saas.get_path_api import GetPathRequest
from mclaw.shared.cm_cloud.cloud_auth import (
    AI_SPACE_DIR_NAME,
    mclaw_allowed_dir,
)
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.postprocess.api_obs import data_dict, err_message, finish
from mclaw.shared.postprocess.merge_normalize import normalize_check_exists_data
from mclaw.shared.postprocess.paths import (
    CloudPathError,
    assert_mclaw_path_prefix,
    compact_segment_name,
    join_cloud_dir_path,
    normalize_cloud_dir_path,
    normalize_name_path,
    split_cloud_dir_path,
)

T = TypeVar('T')

_BATCH_MAX = 100


def _dispatcher():
    return get_cloud_dispatcher()


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def is_folder_like_file_type(file_type: Any) -> bool:
    return str(file_type or '').strip().lower() == 'folder'


def check_exists(parent_file_id: str, file_name: str) -> Dict[str, Any]:
    """检查父目录下是否存在同名项。返回标准化 data dict。"""
    request = SubRequestEnvelope(
        sub_request_list=[
            SubRequest(
                id='0',
                body={
                    'parentFileId': parent_file_id,
                    'fileName': file_name,
                },
            )
        ]
    )
    started = time.perf_counter()
    response = _dispatcher().personal_saas.batch_check_exists(request)
    finish('richlifeApp/personalSaas/file/batchCheckExists', started, response)
    rows = list(getattr(response, 'sub_response_list', None) or [])
    if not rows:
        raise RuntimeError('checkExists 失败：未返回子响应')
    row = rows[0]
    code = str(getattr(row, 'code', '') or '').strip()
    if code != '0000':
        raise RuntimeError(
            f'checkExists 失败: {getattr(row, "message", "") or code or "未知错误"}, '
            f'parent_file_id={parent_file_id!r}'
        )
    return normalize_check_exists_data(getattr(row, 'data', None) or {})


def create_folder(name: str, parent_file_id: str = '/') -> Dict[str, Any]:
    """创建文件夹。返回 data dict。"""
    request = CreateFolderRequest(name=name, parent_file_id=parent_file_id)
    started = time.perf_counter()
    response = _dispatcher().personal_saas.create_folder(request)
    finish('richlifeApp/personalSaas/file/createFolder', started, response)
    if not (response.success and str(response.code or '') == '0000'):
        raise RuntimeError(
            f'创建文件夹失败: {err_message(response, "业务失败")}; '
            f'name={name}, parentFileId={parent_file_id}'
        )
    return data_dict(response)


def get_file_path_map(
    file_ids: list[str],
    *,
    error_cls: type[Exception] = CloudPathError,
) -> dict[str, str]:
    """批量 fileId → 规范化 namePath。"""
    normalized_ids = list(
        dict.fromkeys(str(fid or '').strip() for fid in file_ids if str(fid or '').strip())
    )
    path_map: dict[str, str] = {}
    for chunk in chunked(normalized_ids, _BATCH_MAX):
        request = GetPathRequest(file_ids=list(chunk))
        started = time.perf_counter()
        response = _dispatcher().personal_saas.get_path(request)
        finish('richlifeApp/personalSaas/file/batchGetPath', started, response)
        if str(response.code or '') != '0000':
            raise error_cls(f'batchGetPath 失败: {err_message(response, "业务失败")}')
        items = data_dict(response).get('items') or []
        for row in items:
            if not isinstance(row, dict):
                continue
            if str(row.get('errCode') or '0000') != '0000':
                raise error_cls(str(row.get('message') or f'查询路径失败：{row.get("fileId")}'))
            file_id = str(row.get('fileId') or '').strip()
            if file_id:
                path_map[file_id] = normalize_cloud_dir_path(str(row.get('namePath') or ''))
    return path_map


def get_file_info_map(
    file_ids: list[str],
    *,
    error_cls: type[Exception] = CloudPathError,
) -> dict[str, dict[str, Any]]:
    """批量 fileId → 文件详情映射。"""
    from mclaw.shared.cm_cloud.personal_service import batch_get_all
    from mclaw.shared.postprocess.merge_normalize import parse_batch_get_src_file

    normalized_ids = list(dict.fromkeys(str(fid or '').strip() for fid in file_ids if str(fid or '').strip()))
    if not normalized_ids:
        return {}

    info_map: dict[str, dict[str, Any]] = {}
    dispatcher = _dispatcher()
    for item in batch_get_all(dispatcher, normalized_ids):
        if str(item.get('errCode') or '') != '0000':
            raise error_cls(str(item.get('message') or 'batch_get 失败'))
        info = parse_batch_get_src_file(item)
        if not info:
            continue
        file_id = str(info.get('fileId') or '').strip()
        if not file_id:
            continue
        info_map[file_id] = {
            'fileId': file_id,
            'parentFileId': str(info.get('parentFileId') or '').strip(),
            'fileName': str(info.get('name') or ''),
            'fileExtension': str(info.get('fileExtension') or ''),
            'category': str(info.get('category') or ''),
            'type': str(info.get('type') or ''),
            'size': int(info.get('size') or 0),
            'createdAt': str(info.get('createdAt') or ''),
            'updatedAt': str(info.get('updatedAt') or ''),
            'addressDetail': info.get('addressDetail') or {},
            'mediaMetaInfo': info.get('mediaMetaInfo') or {},
        }
    return info_map


def validate_mclaw_folder_catalog_id(
    catalog_file_id: str,
    *,
    action: str = '转存',
    error_cls: type[Exception] = CloudPathError,
) -> str:
    """校验目标目录 fileId 存在、为文件夹且位于 MClaw 空间，返回规范化路径。"""
    from mclaw.shared.cm_cloud.cli_validate import validate_cloud_file_id

    try:
        normalized_id = validate_cloud_file_id(catalog_file_id, context=action)
    except ValueError as exc:
        raise error_cls(str(exc)) from exc

    info_map = get_file_info_map([normalized_id], error_cls=error_cls)
    info = info_map.get(normalized_id)
    if not info:
        raise error_cls(f'{action}失败：目录 fileId {normalized_id} 不存在或无法查询')

    category = str(info.get('category') or '').strip().lower()
    file_type = str(info.get('type') or '').strip().lower()
    if category != 'folder' and file_type not in ('folder', '2'):
        raise error_cls(
            f'{action}失败：fileId {normalized_id} 不是文件夹，'
            f'当前类型为 {info.get("type") or info.get("category") or "未知"}'
        )

    path_map = get_file_path_map([normalized_id], error_cls=error_cls)
    raw_path = normalize_name_path(path_map.get(normalized_id) or '')
    if not raw_path:
        raise error_cls(f'{action}失败：无法查询 fileId {normalized_id} 的云盘路径')
    parts = split_cloud_dir_path(raw_path)
    try:
        assert_mclaw_path_prefix(
            parts,
            allowed_dir=mclaw_allowed_dir(),
            action=action,
            error_cls=error_cls,
        )
    except error_cls as exc:
        raise error_cls(
            f'{action}失败：由于权限限制，目标目录必须在 "{mclaw_allowed_dir()}" 目录或其子目录中，'
            f'当前路径为 "{join_cloud_dir_path(parts)}"，请让用户改为该空间下的目标文件夹 fileId。'
        ) from exc
    return join_cloud_dir_path(parts)


def resolve_ai_space_folder_id(
    *,
    error_cls: type[Exception] = CloudPathError,
) -> str:
    """定位根目录下已存在的「AI空间」文件夹 fileId（不创建）。"""
    existing = check_exists('/', AI_SPACE_DIR_NAME)
    if not existing.get('exist'):
        raise error_cls(
            f'操作失败：个人云根目录下未找到「{AI_SPACE_DIR_NAME}」，请确认云盘环境'
        )
    file_id = str(existing.get('appFileId') or '').strip()
    if not file_id:
        raise error_cls(f'操作失败：「{AI_SPACE_DIR_NAME}」已存在但未返回 fileId')
    file_type = str(existing.get('fileType') or '').strip().lower()
    if not is_folder_like_file_type(file_type):
        raise error_cls(
            f'操作失败：「{AI_SPACE_DIR_NAME}」存在但不是文件夹（type={file_type!r}）'
        )
    return file_id


def _reuse_existing_folder(
    parent_id: str,
    folder_name: str,
    existing: dict[str, Any],
    *,
    error_cls: type[Exception],
    matched_name: Optional[str] = None,
) -> dict[str, Any]:
    existing_file_id = str(existing.get('appFileId') or '').strip()
    if not existing_file_id:
        raise error_cls(f'复用目录失败：{folder_name} 已存在但未返回 appFileId')
    file_type = str(existing.get('fileType') or '').strip().lower()
    if not file_type:
        raise error_cls(f'复用目录失败：{folder_name} 已存在但未返回 fileType')
    if not is_folder_like_file_type(file_type):
        raise error_cls(
            f'复用目录失败：父目录 {parent_id} 下已存在同名对象 {folder_name}，'
            f'但其类型为 {file_type!r} 而不是文件夹，无法复用为目录'
        )
    out: dict[str, Any] = {'fileId': existing_file_id, 'parentFileId': parent_id}
    out['_segmentAction'] = 'reused_compact' if matched_name else 'reused'
    if matched_name:
        out['_resolvedSegmentName'] = matched_name
    return out


def ensure_folder(
    parent_id: str,
    folder_name: str,
    *,
    error_cls: type[Exception] = CloudPathError,
) -> dict[str, Any]:
    existing = check_exists(parent_id, folder_name)
    if existing.get('exist'):
        return _reuse_existing_folder(
            parent_id, folder_name, existing, error_cls=error_cls
        )
    if any(ch.isspace() for ch in folder_name):
        compact_name = compact_segment_name(folder_name)
        if compact_name and compact_name != folder_name:
            alt = check_exists(parent_id, compact_name)
            if alt.get('exist'):
                return _reuse_existing_folder(
                    parent_id,
                    folder_name,
                    alt,
                    error_cls=error_cls,
                    matched_name=compact_name,
                )
    created = create_folder(folder_name, parent_id)
    created['_segmentAction'] = 'created'
    return created


def ensure_folder_path_parts(
    parts: list[str],
    *,
    start_parent_file_id: str = '/',
    error_cls: type[Exception] = CloudPathError,
) -> dict[str, Any]:
    if not parts:
        raise error_cls('目录路径不能为空')
    parent_id = str(start_parent_file_id or '/').strip() or '/'
    folder: dict[str, Any] = {'fileId': parent_id, 'parentFileId': ''}
    segment_actions: list[str] = []
    for part in parts:
        folder = ensure_folder(parent_id, part, error_cls=error_cls)
        segment_actions.append(str(folder.pop('_segmentAction', 'created')))
        folder.pop('_resolvedSegmentName', None)
        parent_id = str(folder.get('fileId') or '').strip()
        if not parent_id:
            raise error_cls(f'创建目录失败：{part!r} 未返回 fileId')
    folder['_segmentActions'] = segment_actions
    return folder


def ensure_mclaw_dir_path(
    dir_path: str,
    *,
    error_cls: type[Exception] = CloudPathError,
) -> dict[str, Any]:
    """确保 MClaw 下完整路径存在，返回末级目录信息。"""
    parts = split_cloud_dir_path(dir_path)
    if not parts:
        raise error_cls('目录路径不能为空')
    assert_mclaw_path_prefix(
        parts,
        allowed_dir=mclaw_allowed_dir(),
        action='创建目录',
        error_cls=error_cls,
    )
    ai_space_id = resolve_ai_space_folder_id(error_cls=error_cls)
    return ensure_folder_path_parts(
        parts[1:],
        start_parent_file_id=ai_space_id,
        error_cls=error_cls,
    )


__all__ = [
    'check_exists',
    'create_folder',
    'get_file_info_map',
    'get_file_path_map',
    'validate_mclaw_folder_catalog_id',
    'ensure_folder',
    'ensure_folder_path_parts',
    'ensure_mclaw_dir_path',
    'resolve_ai_space_folder_id',
    'chunked',
]
