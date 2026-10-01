#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询最近阅读记录（同步接口）。

书架阅读记录列表：按内容型白名单查询用户最近的阅读/听书记录，
请求即返回最终结果（无 taskId、无轮询）。

接口路径：POST /richlifeApp/bookshelf/readingRecord/list

入参说明：
  - ``allowContentTypeList``：允许查询的内容型白名单
    （1=咪咕云阅读, 5=咪咕云听书, 20=内容平台入库的版权书籍, 100=云盘书籍）。
    **不填时服务端默认 ``[1,5,100]``——缺 20（版权书籍），需全量时须显式传入**。
  - ``contentType``：单内容型精确过滤（可选，与白名单叠加收窄）。

出参 ``data.items`` 为 ``ReadingRecordInfo`` 列表；基类
``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类字段自动填充。

权威来源：``query_personal_dynamic/scripts/find_reading.py``（1:1 移植；
该模块头注释含 API 与前端字段的完整映射说明，本文件只做接口层建模）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.search import search_api_registry


__all__ = [
    'ReadingRecordInfo',
    'ReadingRecordListRequest',
    'ReadingRecordListResponse',
    'ReadingRecordListApi',
    'ALLOW_CONTENT_TYPE_ALL',
]


#: 全量内容型白名单：服务端不传时默认 ``[1,5,100]`` 缺 20，全量查询须显式传入
ALLOW_CONTENT_TYPE_ALL: List[int] = [1, 5, 20, 100]


# ──────────────────────────── 出参子结构 ────────────────────────────


class ReadingRecordInfo(BaseModel):
    """单条阅读记录（RecordInfo）。

    字段以 ``find_reading.py`` 头注释的 API↔前端映射为准：
      - 咪咕类（contentType 1/5）的 ``thirdContentId`` 对应前端 bookId；
        版权/云盘类（20/100）用 ``contentId``
      - ``chapterName`` 仅咪咕平台内容返回（对应前端 title）
      - ``bookId`` 为独立字段（仅已加入书架时返回）
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    content_type: Optional[int] = Field(None, alias='contentType')
    content_name: Optional[str] = Field(None, alias='contentName')
    cover_url: Optional[str] = Field(None, alias='coverUrl')
    content_id: Optional[str] = Field(None, alias='contentId')
    third_content_id: Optional[str] = Field(None, alias='thirdContentId')
    book_id: Optional[str] = Field(None, alias='bookId')
    chapter_id: Optional[str] = Field(None, alias='chapterId')
    chapter_name: Optional[str] = Field(None, alias='chapterName')
    chapter_offset: Optional[int] = Field(None, alias='chapterOffset')
    progress: Optional[int] = Field(None, alias='progress')
    updated_at: Optional[str] = Field(None, alias='updatedAt')


# ──────────────────────────── Request / Response ────────────────────────────


class ReadingRecordListRequest(BaseModel):
    """阅读记录列表入参。

    本接口为 cloudId 体系（无媒体发送型字段），与 ``SyncRequest``
    （sendType/fileUrl/fileId/...）字段不重合，故直接继承 ``BaseModel``，
    对齐 ``image_deduplicate_api.ImageDeduplicateRequest`` 的做法。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    #: 内容型白名单；None 表示不传（服务端默认 [1,5,100]，缺 20）
    allow_content_type_list: Optional[List[int]] = Field(
        None, alias='allowContentTypeList'
    )
    #: 单内容型精确过滤；None 表示不过滤
    content_type: Optional[int] = Field(None, alias='contentType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口要求的 payload（驼峰字段名，过滤未设字段）。"""
        return self.model_dump(by_alias=True, exclude_none=True)


class ReadingRecordListResponse(SyncResponse):
    """阅读记录列表出参：``data.items`` → ``items``（展平后自动填充）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    items: List[ReadingRecordInfo] = Field(default_factory=list, alias='items')


# ──────────────────────────── API 子类 ────────────────────────────


@search_api_registry.register('reading_record_list')
class ReadingRecordListApi(BaseSyncApi):
    """同步接口：查询最近阅读记录。"""

    PATH = '/richlifeApp/bookshelf/readingRecord/list'
    api_category = 'search'
    api_label = '查询最近阅读记录'

    def execute(
        self,
        request: ReadingRecordListRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ReadingRecordListResponse:
        """类型化入口（Response 扩展了 ``items``，须覆盖签名）。"""
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ReadingRecordListResponse:
        """重写基类钩子：用本接口 Response 解析（基类识别不了扩展字段）。"""
        return ReadingRecordListResponse.from_response(raw, trace_id)
