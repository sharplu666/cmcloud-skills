#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云动态查询（legacy 同步接口，转存动态 5/6/7）。

接口路径：POST /richlifeApp/personalDynamic/queryPersonalDynamic

信封与 ``queryFileSchedules`` 同款（非 code=0000 族）：
  - 成功 ``resultCode == '200'``
  - 业务数据在 ``resultData``（非 ``data``）

入参（``QueryPersonalDynamicRequest``，扁平 JSON、无嵌套包装）：
  | 字段 | 必填 | 说明 |
  | startTime | M | 开始时间 ``yyyy-MM-dd HH:mm:ss`` |
  | endTime | M | 结束时间 ``yyyy-MM-dd HH:mm:ss`` |
  | keyword | M | 文件名关键字（可为空串） |
  | pageSize | M | 页大小（int） |
  | dynamicType | M | 动态类型单值 int（转存：5=分享 / 6=圈子 / 7=发现） |
  | nextPageCursor | O | 翻页游标（字符串，上页返回值原样透传） |

出参（``QueryPersonalDynamicResponse``）：``resultData{total, skillFileList,
nextPageCursor}``。实测口径（2026-09-11 真实接口）：
  - ``total`` 为**字符串**（'4'），模型层转 int；
  - ``skillFileList`` 行仅含 ``contentId/dynamicType/dynamicTime/category/type``
    （无 ``name``/``parentFileId``——展示字段由调用方经 batchGet 富化兜底）；
  - ``category`` 为数字字符串（"0" 目录 / "2" 音频 / "3" 视频…），"2"/"3" 用于
    音视频时长/播放进度富化判定；
  - ``nextPageCursor`` 空串/缺省 = 无下一页。

戒律：信封 ``resultCode`` **必须校验**（HTTP 200 不代表业务成功；旧技能只查
HTTP 状态的缺陷不迁）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry

__all__ = [
    'QUERY_DYNAMIC_TYPE_SHARE',
    'QUERY_DYNAMIC_TYPE_CIRCLE',
    'QUERY_DYNAMIC_TYPE_DISCOVER',
    'SkillFileRow',
    'QueryPersonalDynamicRequest',
    'QueryPersonalDynamicResponse',
    'QueryPersonalDynamicApi',
]

#: dynamicType 转存三型（5=分享转存 / 6=圈子转存 / 7=发现转存）
QUERY_DYNAMIC_TYPE_SHARE: int = 5
QUERY_DYNAMIC_TYPE_CIRCLE: int = 6
QUERY_DYNAMIC_TYPE_DISCOVER: int = 7


class SkillFileRow(BaseModel):
    """``skillFileList`` 单行（wire 原生字段；展示字段由调用方富化）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    content_id: str = Field('', alias='contentId')
    dynamic_type: int = Field(0, alias='dynamicType')
    dynamic_time: str = Field('', alias='dynamicTime')
    category: str = Field('', alias='category')
    type: str = Field('', alias='type')
    name: str = Field('', alias='name')
    parent_file_id: str = Field('', alias='parentFileId')

    @field_validator('dynamic_type', mode='before')
    @classmethod
    def _coerce_dynamic_type(cls, v: Any) -> int:
        if v is None or v == '':
            return 0
        return int(v)


class QueryPersonalDynamicRequest(SyncRequest):
    """入参：扁平 JSON（时间 yyyy-MM-dd HH:mm:ss、游标字符串）。"""

    start_time: str = Field(..., alias='startTime')
    end_time: str = Field(..., alias='endTime')
    keyword: str = Field('', alias='keyword')
    page_size: int = Field(10, alias='pageSize')
    dynamic_type: int = Field(..., alias='dynamicType')
    next_page_cursor: str = Field('', alias='nextPageCursor')

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'startTime': self.start_time,
            'endTime': self.end_time,
            'keyword': self.keyword,
            'pageSize': int(self.page_size),
            'dynamicType': int(self.dynamic_type),
        }
        if self.next_page_cursor:
            payload['nextPageCursor'] = self.next_page_cursor
        return payload


class QueryPersonalDynamicResponse(SyncResponse):
    """出参：resultData{total, skillFileList, nextPageCursor}。"""

    result_data: Dict[str, Any] = Field(default_factory=dict, alias='resultData')

    @field_validator('result_data', mode='before')
    @classmethod
    def _coerce_result_data(cls, v: Any) -> Dict[str, Any]:
        return v if isinstance(v, dict) else {}

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'QueryPersonalDynamicResponse':
        """从 ``resultCode`` / ``resultData`` 信封构造（成功 = resultCode=='200'）。"""
        result_code = str(raw.get('resultCode') or '')
        instance = cls(
            success=result_code == '200',
            code=result_code,
            message=str(raw.get('resultMsg') or raw.get('message') or ''),
            trace_id=trace_id,
            result_data=raw.get('resultData') or {},
        )
        object.__setattr__(instance, 'raw', raw)
        return instance

    @property
    def total(self) -> int:
        """总数（wire 为字符串，无损转 int）。"""
        try:
            return int(self.result_data.get('total') or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def skill_file_list(self) -> List[SkillFileRow]:
        rows = self.result_data.get('skillFileList') or []
        if not isinstance(rows, list):
            return []
        return [
            SkillFileRow.model_validate(row)
            for row in rows if isinstance(row, dict)
        ]

    @property
    def next_page_cursor(self) -> str:
        return str(self.result_data.get('nextPageCursor') or '').strip()


@personal_saas_api_registry.register('query_personal_dynamic')
class QueryPersonalDynamicApi(BaseSyncApi):
    """同步接口：个人云动态查询（转存 5/6/7）。"""

    PATH = '/richlifeApp/personalDynamic/queryPersonalDynamic'
    api_category = 'personal_saas'
    api_label = '转存动态查询'

    def execute(
        self,
        request: QueryPersonalDynamicRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> QueryPersonalDynamicResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> QueryPersonalDynamicResponse:
        return QueryPersonalDynamicResponse.from_response(raw, trace_id)
