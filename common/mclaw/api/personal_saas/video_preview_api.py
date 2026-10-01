#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音视频预览信息查询（同步接口，getPreviewInfo）。

接口路径：POST /richlifeApp/personalSaas/videoPreview/getPreviewInfo

信封为 ``{success, code, message, data}``（成功 = success 且 code=='0000'，
与 personalDynamic 族的 resultCode 信封不同）。业务数据在 ``data``：
``{fileId, meta{duration}, previewInfo{url}}``；``duration`` 为秒（字符串或
数字，如 '12.34'），调用方按需转毫秒。

入参（``VideoPreviewRequest``）：
  | 字段 | 必填 | 说明 |
  | fileId | M | 文件 id |
  | category | M | 'audio' / 'video'（字符串词形，非数字） |
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry

__all__ = [
    'VideoPreviewRequest',
    'VideoPreviewResponse',
    'VideoPreviewApi',
]


class VideoPreviewRequest(SyncRequest):
    """入参：fileId + category('audio'/'video')。"""

    file_id: str = Field(..., alias='fileId')
    category: str = Field(..., alias='category')

    def to_payload(self) -> Dict[str, Any]:
        return {'fileId': self.file_id, 'category': self.category}


class VideoPreviewResponse(SyncResponse):
    """出参：data{fileId, meta.duration(秒), previewInfo.url}。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    file_id: str = Field('', alias='fileId')
    duration: str = Field('', alias='duration')
    preview_url: str = Field('', alias='previewUrl')

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'VideoPreviewResponse':
        data = raw.get('data') or {}
        meta = data.get('meta') or {}
        instance = cls(
            success=bool(raw.get('success')) and str(raw.get('code')) == '0000',
            code=str(raw.get('code') or ''),
            message=str(raw.get('message') or ''),
            trace_id=trace_id,
            file_id=str(data.get('fileId') or ''),
            duration=str(meta.get('duration') or ''),
            preview_url=str((data.get('previewInfo') or {}).get('url') or ''),
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


@personal_saas_api_registry.register('video_preview')
class VideoPreviewApi(BaseSyncApi):
    """同步接口：音视频预览信息（时长/预览 URL）。"""

    PATH = '/richlifeApp/personalSaas/videoPreview/getPreviewInfo'
    api_category = 'personal_saas'
    api_label = '查询预览信息'

    def execute(
        self,
        request: VideoPreviewRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> VideoPreviewResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> VideoPreviewResponse:
        return VideoPreviewResponse.from_response(raw, trace_id)
