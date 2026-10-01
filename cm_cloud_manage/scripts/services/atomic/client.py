#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cm_cloud_manage Service 客户端 —— 共享 dispatcher 单例与 ``api_*`` 对外契约。

``services/atomic/search|file|upload`` 为按域拆分的原子封装；本模块负责：
  - 复用共享库进程级单例 ``get_cloud_dispatcher()``（host/鉴权同源 ``mclaw.api.auth``）
  - 将历史 ``api_*`` 函数名映射到各子模块（CLI 只依赖本层，不直接调 ``mclaw.api``）
  - 异步复制 / 移动的「仅提交」原语（轮询留在 CLI）
  - 转发 ``cli_trace`` 可观测性接口
"""

# 须先把 common / common_auth 注入 sys.path。
# ruff: noqa: E402
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..', '..'))
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from mclaw.api.personal_saas.batch_copy_api import BatchCopyRequest
from mclaw.api.operation.batch_move_files_api import BatchMoveFilesRequest
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher

from utils.config import MERGE_SEARCH_PAGE_SIZE, SEARCH_IMAGE_PAGE_SIZE
from services.atomic.file import (
    batch_check_exists,
    batch_download_url,
    batch_file_update,
    batch_get,
    batch_get_all,
    batch_get_path,
    check_exists,
)
from services.atomic.search import (
    build_search_file_param_v3,
    normalize_page_after_input,
    page_after_to_cli_cursor,
    search_merge_file,
)
from mclaw.shared.cm_cloud.personal_service import task_get as personal_task_get
from services.atomic.upload import create_folder, file_complete, file_create
from mclaw.shared.postprocess.merge_normalize import parse_batch_get_src_file

__all__ = [
    'MERGE_SEARCH_PAGE_SIZE',
    'SEARCH_IMAGE_PAGE_SIZE',
    'api_batch_check_exists',
    'api_batch_copy_async',
    'api_batch_download_url',
    'api_batch_file_update',
    'api_batch_get',
    'api_batch_get_all',
    'api_batch_get_path',
    'api_batch_move_async',
    'api_check_exists',
    'api_create_folder',
    'api_file_complete',
    'api_file_create',
    'api_search_merge_file',
    'api_task_get',
    'build_search_file_param_v3',
    'normalize_page_after_input',
    'page_after_to_cli_cursor',
    'parse_batch_get_src_file'
]

_build_search_file_param_v3 = build_search_file_param_v3

def api_search_merge_file(
    search_file_param: Dict[str, Any],
    *,
    page_size: int = MERGE_SEARCH_PAGE_SIZE,
    page_after: Optional[Any] = None,
    sort_infos: Optional[List[Dict[str, Any]]] = None,
    need_total_count: int = 1,
) -> Tuple[List[Dict[str, Any]], int, Any, str]:
    return search_merge_file(
        get_cloud_dispatcher(),
        search_file_param,
        page_size=page_size,
        page_after=page_after,
        sort_infos=sort_infos,
        need_total_count=need_total_count,
    )


def api_batch_get(file_ids: List[str], thumbnail_styles: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    return batch_get(get_cloud_dispatcher(), file_ids, thumbnail_styles=thumbnail_styles)


def api_batch_get_all(
    file_ids: List[str],
    thumbnail_styles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    return batch_get_all(get_cloud_dispatcher(), file_ids, thumbnail_styles=thumbnail_styles)


def api_batch_get_path(file_ids: List[str]) -> List[Dict[str, Any]]:
    return batch_get_path(get_cloud_dispatcher(), file_ids)


def api_batch_check_exists(sub_requests: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return batch_check_exists(get_cloud_dispatcher(), sub_requests)


def api_check_exists(parent_file_id: str, file_name: str) -> Dict[str, Any]:
    return check_exists(get_cloud_dispatcher(), parent_file_id, file_name)


def api_batch_download_url(file_ids: List[str]) -> Dict[str, str]:
    return batch_download_url(get_cloud_dispatcher(), file_ids)


def api_file_create(
    name: str,
    size: int,
    *,
    parent_path: Optional[str] = None,
    parent_file_id: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    return file_create(
        get_cloud_dispatcher(), name, size, parent_path=parent_path, parent_file_id=parent_file_id
    )


def api_file_complete(upload_id: str, file_id: str, content_hash: str) -> bool:
    return file_complete(get_cloud_dispatcher(), upload_id, file_id, content_hash)


def api_create_folder(name: str, parent_file_id: str = '/') -> Dict[str, Any]:
    return create_folder(get_cloud_dispatcher(), name, parent_file_id)


def api_batch_file_update(sub_requests: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return batch_file_update(get_cloud_dispatcher(), sub_requests)


def api_task_get(task_id: str) -> Optional[Dict[str, Any]]:
    return personal_task_get(get_cloud_dispatcher(), task_id)


def api_batch_copy_async(
    file_ids: List[str],
    to_parent_file_id: str,
) -> str:
    request = BatchCopyRequest(
        file_ids=list(file_ids),
        to_parent_file_id=to_parent_file_id,
    )
    try:
        resp = get_cloud_dispatcher().personal_saas.batch_copy(request, poll=False)
    except (RuntimeError, TimeoutError) as exc:
        raise RuntimeError(
            f'批量复制失败: {exc}; toParentFileId={to_parent_file_id}'
        ) from exc
    # 对齐旧契约：提交接口必须 code=='0000'，非 0000 即使带 taskId 也按业务失败处理
    if str(resp.code) != '0000':
        raise RuntimeError(
            f'批量复制失败: code={resp.code} message={resp.message}; '
            f'toParentFileId={to_parent_file_id}'
        )
    return resp.task_id


def api_batch_move_async(file_ids: List[str], to_parent_file_id: str) -> str:
    request = BatchMoveFilesRequest(
        file_ids=list(file_ids),
        to_parent_file_id=to_parent_file_id,
    )
    try:
        resp = get_cloud_dispatcher().operation.batch_move_files(request, poll=False)
    except (RuntimeError, TimeoutError) as exc:
        raise RuntimeError(f'批量移动失败: {exc}') from exc
    # 对齐旧契约：提交接口必须 code=='0000'，非 0000 即使带 taskId 也按业务失败处理
    if str(resp.code) != '0000':
        raise RuntimeError(
            f'批量移动失败: code={resp.code} message={resp.message}'
        )
    return resp.task_id
