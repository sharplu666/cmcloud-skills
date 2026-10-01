#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云上传 Service —— 创建文件、完成上传、建目录。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas.create_folder_api import CreateFolderRequest
from mclaw.api.personal_saas.file_complete_api import FileCompleteRequest
from mclaw.api.personal_saas.file_create_api import FileCreateRequest

from mclaw.shared.postprocess.api_obs import data_dict, err_message, finish

__all__ = ['file_create', 'file_complete', 'create_folder']


def file_create(
    dispatcher: ApiDispatcher,
    name: str,
    size: int,
    *,
    parent_path: Optional[str] = None,
    parent_file_id: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """创建文件（申请上传）。返回 (uploadId, fileId, parentFileId, uploadUrl)。"""
    p_path = (parent_path or '').strip()
    p_fid = (parent_file_id or '').strip()
    if bool(p_path) == bool(p_fid):
        raise RuntimeError('创建文件失败: parentPath 与 parentFileId 互斥，且必须二选一')

    request = FileCreateRequest(
        name=name,
        size=size,
        parent_file_id=p_fid or None,
        parent_path=p_path or None,
    )
    started = time.perf_counter()
    response = dispatcher.personal_saas.file_create(request)
    finish('richlifeApp/personalSaas/file/create', started, response)
    if str(response.code or '') != '0000':
        raise RuntimeError(f'创建文件失败: {err_message(response, "业务失败")}')
    return response.upload_id, response.file_id, response.parent_file_id, response.first_part_upload_url


def file_complete(dispatcher: ApiDispatcher, upload_id: str, file_id: str, content_hash: str) -> bool:
    """完成文件上传。成功返回 True，否则 False。"""
    request = FileCompleteRequest(upload_id=upload_id, file_id=file_id, content_hash=content_hash)
    try:
        started = time.perf_counter()
        response = dispatcher.personal_saas.file_complete(request)
        finish('richlifeApp/personalSaas/file/complete', started, response)
    except RuntimeError:
        return False
    return bool(response.success)


def create_folder(dispatcher: ApiDispatcher, name: str, parent_file_id: str = '/') -> Dict[str, Any]:
    """创建文件夹。返回 data dict（fileId/fileName/parentFileId/exist）。"""
    request = CreateFolderRequest(name=name, parent_file_id=parent_file_id)
    started = time.perf_counter()
    response = dispatcher.personal_saas.create_folder(request)
    finish('richlifeApp/personalSaas/file/createFolder', started, response)
    if not (response.success and str(response.code or '') == '0000'):
        raise RuntimeError(
            f'创建文件夹失败: {err_message(response, "业务失败")}; name={name}, parentFileId={parent_file_id}'
        )
    return data_dict(response)
