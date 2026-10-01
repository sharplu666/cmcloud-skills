#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-by-ids 编排：存在性校验 → folder 检出拒绝 → 文件 id 原样放行。

流程：
  1. ``check_fileids_exist``（batchGet）校验 fileId 真实存在；任一不存在 →
     整体拒绝，``OperationServiceError`` message 带全部缺失 id。
  2. ``api_batch_get_all`` 拿每项 type/name（输入 ≤20 恒单批）；``type=='folder'``
     的项 → ``FolderIdsRejected``（携带 (fileId, 名称) 列表），由 cli 层组
     拒绝回执与 ``next.search`` 指路。
  3. 全为文件 → 按输入顺序原样返回，交 search_by_fileId 一次全量取数。
"""

from __future__ import annotations

from typing import Any, Dict, List

from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.cm_cloud.fileid_validate import check_fileids_exist

from services.atomic.client import api_batch_get_all
from services.errors import OperationServiceError


class FolderIdsRejected(OperationServiceError):
    """输入含文件夹 fileId：整体拒绝；``folders`` 携带 (fileId, 名称) 列表。"""

    def __init__(self, message: str, folders: List[Tuple[str, str]]) -> None:
        super().__init__(message)
        self.folders = list(folders)


def _batch_get_details(file_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """batchGet 拿 ``{fileId: srcFile行}``；失败整体转 ``OperationServiceError``。"""
    try:
        items = api_batch_get_all(list(file_ids))
    except RuntimeError as exc:
        raise OperationServiceError(
            f'查询文件详情失败：{exc}；请停止并交用户决策，勿自动重试'
        ) from exc
    details: Dict[str, Dict[str, Any]] = {}
    for item in items:
        src = item.get('srcFile') if isinstance(item.get('srcFile'), dict) else {}
        fid = str(src.get('fileId') or item.get('fileId') or '').strip()
        if fid:
            details[fid] = src
    return details


def resolve_file_ids(
    file_ids: List[str],
    *,
    dispatcher: Any = None,
) -> List[str]:
    """存在性校验 + folder 检出，返回按输入顺序的文件 fileId 列表。

    任一 fileId 不存在 → 整体拒绝（message 带全部缺失 id）；任一为 folder →
    ``FolderIdsRejected``。
    """
    unique_ids = list(dict.fromkeys(fid for fid in file_ids if fid))
    dispatcher = dispatcher or get_cloud_dispatcher()

    exists = check_fileids_exist(unique_ids, dispatcher)
    missing = [fid for fid, ok in zip(unique_ids, exists) if not ok]
    if missing:
        raise OperationServiceError(f'以下 fileId 不存在或不可访问: {missing}')

    details = _batch_get_details(unique_ids)
    folders = [
        (fid, str((details.get(fid) or {}).get('name') or '').strip() or fid)
        for fid in unique_ids
        if str((details.get(fid) or {}).get('type') or '').strip() == 'folder'
    ]
    if folders:
        listing = '、'.join(f'{name}（fileId：{fid}）' for fid, name in folders)
        raise FolderIdsRejected(
            f'以下 fileId 是文件夹，本命令仅支持文件：{listing}', folders
        )
    return unique_ids


__all__ = ['resolve_file_ids', 'FolderIdsRejected']
