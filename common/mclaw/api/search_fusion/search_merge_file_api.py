#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云文件类整合搜索接口（Pydantic v2）。

封装搜索平台文件搜索（searchType=File）与个人动态文件搜索（searchType=FileDynamic）。

接口路径：POST /richlifeApp/aiService/api/text/intelligent/search/merge/file
同步返回结果（无 taskId、无轮询）。

入参/出参子结构 MergePageInfo / SearchFileParamV3 / SearchFileDynamicParam / File
共享自同目录 `_models.py`；本文件只定义本接口独有的 MergeFileSearchParam 与
Request/Response/Api 子类。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.search_fusion import search_fusion_api_registry
from mclaw.utils.settings import ApiTimeoutSettings
from mclaw.api.search_fusion._models import (
    File,
    MergePageInfo,
    SearchFileDynamicParam,
    SearchFileParamV3,
    apply_ai_score_defaults,
)
from mclaw.api.search_fusion._redact import redact_search_result, strip_keywords_tag


__all__ = [
    'MergeFileSearchParam',
    'MergeFileSearchRequest',
    'MergeFileSearchResponse',
    'MergeFileSearchApi',
]


# ──────────────────────────── 入参子结构（本接口独有） ────────────────────────────


class MergeFileSearchParam(BaseModel):
    """文件类整合搜索条件。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    # File：个人云搜文件；FileDynamic：个人动态搜文件
    search_type: str = Field('File', alias='searchType')
    # search_type=File 时使用
    search_file_param: Optional[SearchFileParamV3] = Field(None, alias='searchFileParam')
    # search_type=FileDynamic 时使用
    search_file_dynamic_param: Optional[SearchFileDynamicParam] = Field(
        None, alias='searchFileDynamicParam'
    )
    page_info: Optional[MergePageInfo] = Field(None, alias='pageInfo')


# ──────────────────────────── Request / Response ────────────────────────────


class MergeFileSearchRequest(SyncRequest):
    """入参：searchParam 嵌套结构。

    父类通用字段（send_type/file_url/...）对本接口无意义，to_payload 只输出
    searchParam。
    """

    search_param: MergeFileSearchParam = Field(
        default_factory=MergeFileSearchParam, alias='searchParam'
    )

    def to_payload(self) -> Dict[str, Any]:
        return {
            'searchParam': self.search_param.model_dump(
                by_alias=True, exclude_none=True
            )
        }


class MergeFileSearchResponse(SyncResponse):
    """出参：fileList + totalCount + pageAfter。

    基类 SyncResponse.from_response 已默认展平 data 嵌套层，
    fileList/totalCount/pageAfter 会被自动填充，无需重写 from_response。
    """

    file_list: List[File] = Field(default_factory=list, alias='fileList')
    total_count: Optional[int] = Field(None, alias='totalCount')
    page_after: Optional[List[Any]] = Field(None, alias='pageAfter')


# ──────────────────────────── API 子类 ────────────────────────────


@search_fusion_api_registry.register('search_merge_file')
class MergeFileSearchApi(BaseSyncApi):
    """同步接口：个人云文件类整合搜索。"""

    PATH = '/richlifeApp/aiService/api/text/intelligent/search/merge/file'
    TIMEOUT = ApiTimeoutSettings.SEARCH_MERGE_FILE_SEC
    api_category = 'search'
    api_label = '个人云文件类整合搜索'
    # 业务码兜底重试：只读幂等查询，命中清单错误码时同参重发 1 次（默认空集=休眠）
    BUSINESS_CODE_RETRY_ENABLED = True

    def _build_result_dict(
        self, response: MergeFileSearchResponse, *args: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        """日志脱敏：移除 thumbnailUrl/contentHash/contentHashAlgorithm，
        截断 aiAnalysisInfo.content 到前 10 字符。详见 ``_redact.redact_search_result``。"""
        return redact_search_result(response.raw)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> MergeFileSearchResponse:
        strip_keywords_tag(raw)
        return MergeFileSearchResponse.from_response(raw, trace_id)

    def _build_result(
        self,
        response: MergeFileSearchResponse,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> MergeFileSearchResponse:
        """个人云搜索/个人动态搜索：image 类 File 缺 ``aiAnalysisInfo.score`` 时补 1。"""
        apply_ai_score_defaults(response.file_list, 1.0)
        return response
