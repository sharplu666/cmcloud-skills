#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建文件 / 申请上传（同步接口，上传第一阶段）。

接口路径：POST /richlifeApp/personalSaas/file/create

本封装仅包含单分片上传所需字段；完整入参含 PartInfo、contentHash 等。

入参（``FileCreateRequest.to_payload()``）：
  | 字段 | 必填 | 说明 |
  | name | M | 文件名 |
  | size | M | 字节数 |
  | type | M | 固定 ``file`` |
  | parentFileId / parentPath | O | 二选一，互斥 |
  | fileRenameMode | O | 默认 force_rename |
  | partInfos | M | 单分片 ``[{partNumber:1, partSize:size}]`` |

出参（``FileCreateResponse``）：
  | 字段 | 必填 | 说明 |
  | parentFileId | M | 父目录 id |
  | fileId | M | 文件 id |
  | type | M | file / folder |
  | fileName | M | 最终文件名（可能重命名） |
  | rapidUpload | M | 是否秒传 |
  | uploadId | O | 上传 id，秒传为空 |
  | partInfos | O | 分片 uploadUrl 列表 |
  | exist | O | refuse/auto_rename 同名时 |
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry


__all__ = [
    'FileCreateRequest',
    'FileCreateResponse',
    'FileCreateApi',
]


class FileCreateRequest(SyncRequest):
    """入参：单分片上传申请。"""

    name: str
    size: int
    parent_path: Optional[str] = Field(None, alias='parentPath')
    parent_file_id: Optional[str] = Field(None, alias='parentFileId')
    file_rename_mode: str = Field('force_rename', alias='fileRenameMode')

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'name': self.name,
            'size': self.size,
            'type': 'file',
            'fileRenameMode': self.file_rename_mode,
            'partInfos': [{'partNumber': 1, 'partSize': self.size}],
        }
        if self.parent_file_id:
            payload['parentFileId'] = self.parent_file_id
        else:
            payload['parentPath'] = self.parent_path
        return payload


class FileCreateResponse(SyncResponse):
    """出参：uploadId / fileId / parentFileId / partInfos。"""

    upload_id: str = Field('', alias='uploadId')
    file_id: str = Field('', alias='fileId')
    parent_file_id: str = Field('', alias='parentFileId')
    file_name: str = Field('', alias='fileName')
    type: str = ''
    rapid_upload: bool = Field(False, alias='rapidUpload')
    exist: Optional[bool] = None
    part_infos: List[Dict[str, Any]] = Field(default_factory=list, alias='partInfos')

    @property
    def first_part_upload_url(self) -> str:
        """首个分片的预签名上传地址。"""
        if self.part_infos and isinstance(self.part_infos[0], dict):
            return str(self.part_infos[0].get('uploadUrl') or '')
        return ''


@personal_saas_api_registry.register('file_create')
class FileCreateApi(BaseSyncApi):
    """同步接口：创建文件并申请上传。"""

    PATH = '/richlifeApp/personalSaas/file/create'
    api_category = 'personal_saas'
    api_label = '创建文件'

    def execute(
        self,
        request: FileCreateRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> FileCreateResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> FileCreateResponse:
        return FileCreateResponse.from_response(raw, trace_id)
