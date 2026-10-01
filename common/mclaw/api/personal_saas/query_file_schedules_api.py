#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按文件 ID 查询音视频播放进度（同步接口）。

接口路径：POST /richlifeApp/personalDynamic/queryFileSchedules

单次最多 200 条 fileId；``contentTypeList`` 2=音频、3=视频。

信封与其它 personal_saas 接口不同：
  - 成功 ``resultCode == '200'``（非 code=0000）
  - 业务数据在 ``resultData``（非 ``data``）

入参（``QueryFileSchedulesRequest``）：
  | 字段 | 必填 | 说明 |
  | fileIdList | M | 文件 id 列表，最多 200 |
  | contentTypeList | M | 内容类型，默认 [2, 3] |

出参（``QueryFileSchedulesResponse``）：
  | 字段 | 必填 | 说明 |
  | resultCode | M | 200 成功 |
  | resultMsg | O | 描述 |
  | resultData | O | PlayInfo[] |

PlayInfo：
  | 字段 | 必填 | 说明 |
  | id | M | 记录 id |
  | fileId | M | 文件 id |
  | isPlay | M | 0 未播放 / 1 已播放 |
  | playbackProgress | M | 进度毫秒（接口可能为字符串） |
  | playLastTime | O | 播放时间 |
  | contentType | M | 2 音频 / 3 视频 |
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry


__all__ = [
    'QueryFileSchedulesRequest',
    'PlayInfo',
    'QueryFileSchedulesResponse',
    'QueryFileSchedulesApi',
]


class QueryFileSchedulesRequest(SyncRequest):
    """入参：fileIdList + contentTypeList。"""

    file_id_list: List[str] = Field(..., alias='fileIdList')
    content_type_list: List[int] = Field(default_factory=lambda: [2, 3], alias='contentTypeList')

    def to_payload(self) -> Dict[str, Any]:
        return {
            'fileIdList': list(self.file_id_list),
            'contentTypeList': list(self.content_type_list),
        }


class PlayInfo(BaseModel):
    """单条播放进度记录（PlayInfo）。

    ``playbackProgress`` 在响应中可能为字符串，校验前会转换为 int。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    file_id: str = Field('', alias='fileId')
    playback_progress: int = Field(0, alias='playbackProgress')
    is_play: int = Field(0, alias='isPlay')
    play_last_time: str = Field('', alias='playLastTime')
    content_type: int = Field(0, alias='contentType')
    id: Optional[Union[int, str]] = None

    @field_validator('playback_progress', mode='before')
    @classmethod
    def _coerce_playback_progress(cls, v: Any) -> int:
        if v is None or v == '':
            return 0
        return int(v)

    @field_validator('id', mode='before')
    @classmethod
    def _coerce_id(cls, v: Any) -> Optional[Union[int, str]]:
        if v is None or v == '':
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return str(v)


class QueryFileSchedulesResponse(SyncResponse):
    """出参：resultData（PlayInfo 列表）。"""

    result_data: List[PlayInfo] = Field(default_factory=list, alias='resultData')

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'QueryFileSchedulesResponse':
        """从 ``resultCode`` / ``resultData`` 信封构造。"""
        result_code = str(raw.get('resultCode') or '')
        items = [
            PlayInfo.model_validate(row)
            for row in (raw.get('resultData') or [])
            if isinstance(row, dict)
        ]
        instance = cls(
            success=result_code == '200',
            code=result_code,
            message=str(raw.get('resultMsg') or raw.get('message') or ''),
            trace_id=trace_id,
            result_data=items,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


@personal_saas_api_registry.register('query_file_schedules')
class QueryFileSchedulesApi(BaseSyncApi):
    """同步接口：查询音视频播放进度。"""

    PATH = '/richlifeApp/personalDynamic/queryFileSchedules'
    api_category = 'personal_saas'
    api_label = '查询播放进度'

    def execute(
        self,
        request: QueryFileSchedulesRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> QueryFileSchedulesResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> QueryFileSchedulesResponse:
        return QueryFileSchedulesResponse.from_response(raw, trace_id)
