#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量获取文件下载地址（同步接口）。

接口路径：POST /richlifeApp/personalSaas/file/batchGetDownloadUrl

单次最多 100 个 fileId；下载二阶段为对象存储直链。

入参（``BatchGetDownloadUrlRequest``）：
  | 字段 | 必填 | 类型 | 说明 |
  | fileIds | M | String[] | 文件 id 列表，最多 100 |

出参（``data.items`` → ``BatchGetDownloadUrlResponse.items``）：
  DownloadUrlInfo（``DownloadUrlItem``）：
  | 字段 | 必填 | 说明 |
  | fileId | M | 文件 id |
  | url | M | 下载地址 |
  | expiration | M | 过期时间 RFC3339 |
  | size | M | 文件大小 byte |
  | errCode | O | 批量场景 per-item 错误码，0000 成功 |
  | message | O | 失败原因 |
  | cdnUrl | O | CDN 地址 |
  | cdnSwitch | O | 是否 CDN |
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry


__all__ = [
    'BatchGetDownloadUrlRequest',
    'DownloadUrlItem',
    'BatchGetDownloadUrlResponse',
    'BatchGetDownloadUrlApi',
]


class BatchGetDownloadUrlRequest(SyncRequest):
    """入参：fileIds。"""

    file_ids: List[str] = Field(..., alias='fileIds')

    def to_payload(self) -> Dict[str, Any]:
        return {'fileIds': list(self.file_ids)}


class DownloadUrlItem(BaseModel):
    """单个文件的下载地址结果（DownloadUrlInfo）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    file_id: str = Field('', alias='fileId')
    err_code: str = Field('', alias='errCode')
    message: str = ''
    url: str = ''
    expiration: str = ''
    size: int = 0
    cdn_url: str = Field('', alias='cdnUrl')
    cdn_switch: Optional[bool] = Field(None, alias='cdnSwitch')


class BatchGetDownloadUrlResponse(SyncResponse):
    """出参：items。"""

    items: List[DownloadUrlItem] = Field(default_factory=list)


@personal_saas_api_registry.register('batch_get_download_url')
class BatchGetDownloadUrlApi(BaseSyncApi):
    """同步接口：批量获取文件下载地址。"""

    PATH = '/richlifeApp/personalSaas/file/batchGetDownloadUrl'
    api_category = 'personal_saas'
    api_label = '批量获取下载地址'

    def execute(
        self,
        request: BatchGetDownloadUrlRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> BatchGetDownloadUrlResponse:
        from mclaw.api.native_adapters import (
                    fanout_get_download_url,
            native_user_id,
        )
        if True:
            # 通用(app)后端：原生 file/getDownloadUrl 仅接受单 fileId，逐个取地址后组装 items。
            raw = fanout_get_download_url(
                self.host, list(request.file_ids), self._auth,
                user_id=native_user_id(),
                timeout=kwargs.get('timeout', self.TIMEOUT),
                max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
                retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
                logger=self.logger,
            )
            return self._parse_response(raw, '', *args, **kwargs)
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> BatchGetDownloadUrlResponse:
        return BatchGetDownloadUrlResponse.from_response(raw, trace_id)
