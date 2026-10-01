#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""personal_saas 共享 BaseModel（Pydantic v2）。

存放被多个端点复用的请求/响应子结构：
  - ``BatchGetFile`` / ``ThumbnailInfo``：``batchGet`` 的 ``srcFile``
  - ``SubRequest`` / ``SubResponseItem`` / ``SubRequestEnvelope`` / ``SubResponseEnvelope``：
    ``batchCheckExists`` 与 ``batchUpdate`` 共用的 ``subRequestList`` / ``subResponseList`` 信封

字段命名：Python 用 snake_case，``Field(alias=...)`` 映射 API 驼峰字段名。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import SyncRequest, SyncResponse


_MODEL_CONFIG = ConfigDict(populate_by_name=True, extra='ignore')


__all__ = [
    'BatchGetFile',
    'ThumbnailInfo',
    'SubRequest',
    'SubResponseItem',
    'SubRequestEnvelope',
    'SubResponseEnvelope',
]


class ThumbnailInfo(BaseModel):
    """缩略图条目（``ThumbnailInfo``）。

    对应 ``batchGet`` / ``list`` 等接口返回的 ``thumbnailUrls`` 数组元素。
    """

    model_config = _MODEL_CONFIG

    style: str = ''
    url: Optional[str] = None


class BatchGetFile(BaseModel):
    """``batchGet`` / ``fileGet`` 的 ``srcFile`` 文件结构。

    与 ``search_fusion.File`` 分离：``type=folder`` 时服务端常省略 ``size``、``contentHash``、``contentHashAlgorithm``，
    模型层以 ``0`` / ``''`` 作为缺省值；完整原始字段见 ``response.raw``。

    字段映射说明：
      - ``thumbnailUrls``（数组）映射为 ``thumbnail_urls``；``thumbnailUrl`` 单字段保留兼容。
      - ``userTags``、``revisionId``、``metadataAuditInfo`` 等未建模字段由 ``extra='ignore'`` 忽略。
    """

    model_config = _MODEL_CONFIG

    file_id: str = Field(..., alias='fileId')
    parent_file_id: str = Field('', alias='parentFileId')
    name: str = Field(...)
    content: Optional[str] = None
    name_path: Optional[str] = Field(None, alias='namePath')
    type: str = Field(...)  # file / folder
    category: str = ''
    created_at: str = Field('', alias='createdAt')
    updated_at: Optional[str] = Field(None, alias='updatedAt')
    local_created_at: Optional[str] = Field(None, alias='localCreatedAt')
    local_updated_at: Optional[str] = Field(None, alias='localUpdatedAt')
    size: int = 0
    file_extension: Optional[str] = Field(None, alias='fileExtension')
    thumbnail_url: Optional[str] = Field(None, alias='thumbnailUrl')
    thumbnail_urls: List[ThumbnailInfo] = Field(
        default_factory=list, alias='thumbnailUrls'
    )
    content_hash: str = Field('', alias='contentHash')
    content_hash_algorithm: str = Field('', alias='contentHashAlgorithm')
    starred: Optional[bool] = None


class SubRequest(BaseModel):
    """子请求：携带子请求 ID 与原样透传的请求体。"""

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    id: str
    body: Dict[str, Any] = Field(default_factory=dict)


class SubResponseItem(BaseModel):
    """子响应：与子请求 ID 对应的结果。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    id: str = ''
    code: str = ''
    message: str = ''
    data: Dict[str, Any] = Field(default_factory=dict)


class SubRequestEnvelope(SyncRequest):
    """``subRequestList`` 信封入参。

    每个子请求形如 ``{'id': ..., 'body': {...}}``，body 内字段由各端点决定。
    """

    sub_request_list: List[SubRequest] = Field(
        default_factory=list, alias='subRequestList'
    )

    def to_payload(self) -> Dict[str, Any]:
        return {
            'subRequestList': [
                {'id': item.id, 'body': item.body} for item in self.sub_request_list
            ]
        }


class SubResponseEnvelope(SyncResponse):
    """``subResponseList`` 信封出参。"""

    sub_response_list: List[SubResponseItem] = Field(
        default_factory=list, alias='subResponseList'
    )

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'SubResponseEnvelope':
        """解析 ``data.subResponseList`` 为 ``SubResponseItem`` 列表。"""
        data = raw.get('data') or {}
        items = [
            SubResponseItem.model_validate(row)
            for row in (data.get('subResponseList') or [])
            if isinstance(row, dict)
        ]
        instance = cls(
            success=bool(raw.get('success')),
            code=raw.get('code', ''),
            message=raw.get('message', ''),
            trace_id=trace_id,
            sub_response_list=items,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance
