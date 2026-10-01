#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量获取文件详情（同步接口）。

接口路径：POST /richlifeApp/personalSaas/file/batchGet

单次最多 100 个 fileId，请求即返回结果。

入参（Request → ``BatchGetRequest.to_payload()``）：
  | 字段 | 必填 | 类型 | 说明 |
  | fileIds | M | String[] | 文件 id 列表，最多 100 |
  | thumbnailStyleList | O | String[] | 缩略图样式 Small/Middle/Big/Large，默认 Small |

出参（Response ``data`` 展平为 ``BatchGetResponse``）：
  | 字段 | 必填 | 类型 | 说明 |
  | batchFileResults | M | FileResult[] | 每个 fileId 一条结果 |

FileResult（``BatchGetItem``）：
  | 字段 | 必填 | 类型 | 说明 |
  | srcFile | O | File | 成功时的文件详情，见 ``BatchGetFile`` |
  | errCode | O | String | 0000 或 null 表示成功 |
  | message | O | String | 失败原因 |
  | fileId | O | String | 部分响应在条目顶层重复 fileId |

BatchGetFile（``srcFile``）主要字段：
  | 字段 | 必填 | 说明 |
  | fileId, parentFileId, name, type | M | 文件标识 |
  | category, createdAt, updatedAt | M/O | 分类与时间 |
  | size, contentHash, contentHashAlgorithm | 文件 M | 目录类型响应可能省略，缺省 0/'' |
  | fileExtension, starred, localCreatedAt | O | 可选属性 |
  | thumbnailUrls | O | ``ThumbnailInfo[]``（style, url） |
  | mediaMetaInfo, addressDetail, userTags 等 | O | 未建模，见 ``response.raw`` |
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry
from mclaw.api.personal_saas._models import BatchGetFile


__all__ = [
    'BatchGetRequest',
    'BatchGetItem',
    'BatchGetResponse',
    'BatchGetApi',
]


class BatchGetRequest(SyncRequest):
    """入参：fileIds + 可选缩略图样式。"""

    file_ids: List[str] = Field(..., alias='fileIds')
    thumbnail_style_list: Optional[List[str]] = Field(None, alias='thumbnailStyleList')

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'fileIds': list(self.file_ids)}
        if self.thumbnail_style_list:
            payload['thumbnailStyleList'] = list(self.thumbnail_style_list)
        return payload


class BatchGetItem(BaseModel):
    """单个文件的查询结果（FileResult）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    err_code: str = Field('', alias='errCode')
    message: str = ''
    file_id: str = Field('', alias='fileId')
    src_file: Optional[BatchGetFile] = Field(None, alias='srcFile')


class BatchGetResponse(SyncResponse):
    """出参：batchFileResults。"""

    batch_file_results: List[BatchGetItem] = Field(
        default_factory=list, alias='batchFileResults'
    )


def _is_batch_get_src_file_complete(src: Any) -> bool:
    """``srcFile`` 是否含 batchGet 成功条目所需的最小字段。"""
    if not isinstance(src, dict):
        return False
    return (
        bool(str(src.get('fileId') or '').strip())
        and bool(str(src.get('name') or '').strip())
        and bool(str(src.get('type') or '').strip())
    )


def _normalize_batch_file_result_row(item: Any) -> Any:
    """失败或残缺 ``srcFile`` 置 ``None``，避免整包 Pydantic 校验失败。

    服务端对 ``errCode != 0000``（如 ``04000010 资源不存在``）仍可能返回
    ``srcFile: {fileId}`` 占位；批内部分失败是合法语义，条目级 ``errCode`` 为准。
    """
    if not isinstance(item, dict):
        return item
    row = dict(item)
    err_code = str(row.get('errCode') or '0000').strip() or '0000'
    if err_code != '0000' or not _is_batch_get_src_file_complete(row.get('srcFile')):
        row['srcFile'] = None
    return row


def _normalize_batch_get_response_data(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    results = out.get('batchFileResults')
    if isinstance(results, list):
        out['batchFileResults'] = [_normalize_batch_file_result_row(x) for x in results]
    return out


@personal_saas_api_registry.register('batch_get')
class BatchGetApi(BaseSyncApi):
    """同步接口：批量获取文件详情。"""

    PATH = '/richlifeApp/personalSaas/file/batchGet'
    api_category = 'personal_saas'
    api_label = '批量获取文件详情'

    def execute(
        self,
        request: BatchGetRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> BatchGetResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> BatchGetResponse:
        parse_raw = dict(raw)
        data = parse_raw.get('data')
        if isinstance(data, dict):
            parse_raw = {**parse_raw, 'data': _normalize_batch_get_response_data(data)}
        response = BatchGetResponse.from_response(parse_raw, trace_id)
        # 保留服务端原始 JSON，供 data_dict() 与排查使用
        object.__setattr__(response, 'raw', raw)
        return response
