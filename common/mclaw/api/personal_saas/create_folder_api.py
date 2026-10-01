#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建文件夹（同步接口）。

接口路径：POST /richlifeApp/personalSaas/file/createFolder

``fileRenameMode=refuse`` 时若同名已存在，响应 ``data.exist`` 为 true。

入参（``CreateFolderRequest``）：
  | 字段 | 必填 | 说明 |
  | name | M | 文件夹名 |
  | parentFileId | O | 父目录，默认 ``'/'`` |
  | type | M | 固定 ``folder`` |
  | fileRenameMode | O | 默认 refuse |

出参（``CreateFolderResponse``）：
  | 字段 | 必填 | 说明 |
  | fileId | M | 文件夹 id |
  | fileName | M | 最终名称 |
  | parentFileId | O | 父目录 id |
  | type | O | folder |
  | exist | O | refuse 且同名已存在时为 true |
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry


__all__ = [
    'CreateFolderRequest',
    'CreateFolderResponse',
    'CreateFolderApi',
]


class CreateFolderRequest(SyncRequest):
    """入参：name / parentFileId。"""

    name: str
    parent_file_id: str = Field('/', alias='parentFileId')
    file_rename_mode: str = Field('refuse', alias='fileRenameMode')

    def to_payload(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'parentFileId': self.parent_file_id,
            'type': 'folder',
            'fileRenameMode': self.file_rename_mode,
        }


class CreateFolderResponse(SyncResponse):
    """出参：fileId / fileName / parentFileId / exist。"""

    file_id: str = Field('', alias='fileId')
    file_name: str = Field('', alias='fileName')
    parent_file_id: str = Field('', alias='parentFileId')
    type: str = ''
    exist: bool = False


@personal_saas_api_registry.register('create_folder')
class CreateFolderApi(BaseSyncApi):
    """同步接口：创建文件夹。"""

    PATH = '/richlifeApp/personalSaas/file/createFolder'
    api_category = 'personal_saas'
    api_label = '创建文件夹'

    def execute(
        self,
        request: CreateFolderRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> CreateFolderResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> CreateFolderResponse:
        return CreateFolderResponse.from_response(raw, trace_id)
