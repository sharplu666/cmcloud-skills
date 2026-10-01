#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完成文件上传（同步接口，上传第三阶段）。

接口路径：POST /richlifeApp/personalSaas/file/complete

入参（``FileCompleteRequest``）：
  | 字段 | 必填 | 说明 |
  | fileId | M | 文件 id |
  | uploadId | M | 上传 id |
  | contentHash | M | 64 位 hash，须与 create 阶段提交值一致 |
  | contentHashAlgorithm | M | 当前仅 sha256 |

出参：服务端返回 ``File`` 结构；本封装返回 ``SyncResponse``，完整字段见 ``response.raw``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry


__all__ = [
    'FileCompleteRequest',
    'FileCompleteApi',
]


class FileCompleteRequest(SyncRequest):
    """入参：uploadId / fileId / contentHash。"""

    upload_id: str = Field(..., alias='uploadId')
    file_id: str = Field(..., alias='fileId')
    content_hash: str = Field(..., alias='contentHash')
    content_hash_algorithm: str = Field('SHA256', alias='contentHashAlgorithm')

    def to_payload(self) -> Dict[str, Any]:
        return {
            'uploadId': self.upload_id,
            'fileId': self.file_id,
            'contentHash': self.content_hash,
            'contentHashAlgorithm': self.content_hash_algorithm,
        }


@personal_saas_api_registry.register('file_complete')
class FileCompleteApi(BaseSyncApi):
    """同步接口：完成文件上传。"""

    PATH = '/richlifeApp/personalSaas/file/complete'
    api_category = 'personal_saas'
    api_label = '完成文件上传'

    def execute(
        self,
        request: FileCompleteRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SyncResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
