#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云图片类整合搜索接口（Pydantic v2）。

封装语义搜图（searchType=SemanticImage）、个人云搜图（searchType=ImageFile）、
个人动态搜图（searchType=ImageDynamic）与图文搜人（searchType=SemanticImagePerson）。

接口路径：POST /richlifeApp/aiService/api/text/intelligent/search/merge/image
同步返回结果（无 taskId、无轮询）。

入参/出参子结构 MergePageInfo / SearchFileParamV3 / SearchFileDynamicParam / File /
SelectFaceItem / AmbiguityItem 共享自同目录 `_models.py`；本文件只定义本接口独有的
SearchImageParamV2 / SearchImagePersonParam / MergeImageSearchParam 与
Request/Response/Api 子类。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.search_fusion import search_fusion_api_registry
from mclaw.utils.settings import ApiTimeoutSettings
from mclaw.api.search_fusion._models import (
    AmbiguityItem,
    File,
    MergePageInfo,
    RecognizeFaceInfo,
    SearchFileDynamicParam,
    SearchFileParamV3,
    SelectFaceItem,
    apply_ai_score_defaults,
)
from mclaw.api.search_fusion._redact import redact_search_result, strip_keywords_tag


__all__ = [
    'SearchImageParamV2',
    'SearchImagePersonParam',
    'MergeImageSearchParam',
    'MergeImageSearchRequest',
    'MergeImageSearchResponse',
    'MergeImageSearchApi',
]


# ──────────────────────────── 入参子结构（本接口独有） ────────────────────────────

#: 这两种 searchType 的 image 缺 ``aiAnalysisInfo.score`` 时补 0（其余 searchType 补 1）
_SEMANTIC_SEARCH_TYPES = ('SemanticImage', 'SemanticImagePerson')


class SearchImageParamV2(BaseModel):
    """语义搜图条件（searchType=SemanticImage 时使用）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    text: Optional[str] = None
    # 1 按拍摄时间倒序（默认），2 按相关度倒序
    sort_type: Optional[int] = Field(None, alias='sortType')
    # 大模型语义理解信息
    semantic_info: Optional[str] = Field(None, alias='semanticInfo')
    # true 只返回文件 id，不走个人云；false 走个人云
    is_original: Optional[bool] = Field(None, alias='isOriginal')
    # 是否进行重排，默认 true；分页参数大于 500 时传 true 也无法重排
    use_rerank: Optional[bool] = Field(None, alias='useRerank')
    scene: Optional[str] = None


class SearchImagePersonParam(BaseModel):
    """图文搜人条件（searchType=SemanticImage / SemanticImagePerson 时使用）。

    ``text`` 必填；``fileIdList`` 在图片理解路径必填、选脸路径可为空；
    ``selectFaceList`` 为用户在参考图上勾选的人脸框；
    ``skipMultimodal=true`` 时跳过多模态理解直接搜索，需配合
    ``recognizeFaceInfo``（face/recognize 图片理解结果）原样回传。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    text: str = Field(...)
    file_id_list: Optional[List[str]] = Field(None, alias='fileIdList')
    select_face_list: Optional[List[SelectFaceItem]] = Field(None, alias='selectFaceList')
    # 大模型语义理解信息
    semantic_info: Optional[str] = Field(None, alias='semanticInfo')
    # true=跳过多模态（已有 recognizeFaceInfo 时直接搜索）；false/缺省=原逻辑
    skip_multimodal: Optional[bool] = Field(None, alias='skipMultimodal')
    # 人脸图片理解结果（rewriteQuery + 筛选/选择后的人脸列表），skipMultimodal=true 时传入
    recognize_face_info: Optional[RecognizeFaceInfo] = Field(None, alias='recognizeFaceInfo')


class MergeImageSearchParam(BaseModel):
    """图片类整合搜索条件。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    # SemanticImage：语义搜图；ImageFile：个人云搜图；ImageDynamic：个人动态搜图；SemanticImagePerson：图文搜人
    search_type: str = Field('SemanticImage', alias='searchType')
    # search_type=ImageFile 时使用
    search_file_param: Optional[SearchFileParamV3] = Field(None, alias='searchFileParam')
    # search_type=SemanticImage 时使用
    search_image_param: Optional[SearchImageParamV2] = Field(None, alias='searchImageParam')
    # search_type=ImageDynamic 时使用
    search_file_dynamic_param: Optional[SearchFileDynamicParam] = Field(
        None, alias='searchFileDynamicParam'
    )
    # search_type=SemanticImagePerson 时使用
    search_image_person_param: Optional[SearchImagePersonParam] = Field(
        None, alias='searchImagePersonParam'
    )
    page_info: Optional[MergePageInfo] = Field(None, alias='pageInfo')


# ──────────────────────────── Request / Response ────────────────────────────


class MergeImageSearchRequest(SyncRequest):
    """入参：searchParam 嵌套结构。

    父类通用字段（send_type/file_url/...）对本接口无意义，to_payload 只输出
    searchParam。
    """

    search_param: MergeImageSearchParam = Field(
        default_factory=MergeImageSearchParam, alias='searchParam'
    )

    def to_payload(self) -> Dict[str, Any]:
        return {
            'searchParam': self.search_param.model_dump(
                by_alias=True, exclude_none=True
            )
        }


class MergeImageSearchResponse(SyncResponse):
    """出参：fileList + totalCount + pageAfter + ambiguityList + semanticInfo。

    基类 SyncResponse.from_response 已默认展平 data 嵌套层，
    fileList/totalCount/pageAfter/ambiguityList/semanticInfo 会被自动填充，无需重写 from_response。
    """

    file_list: List[File] = Field(default_factory=list, alias='fileList')
    total_count: Optional[int] = Field(None, alias='totalCount')
    page_after: Optional[List[Any]] = Field(None, alias='pageAfter')
    # searchType=SemanticImagePerson 且歧义时返回
    ambiguity_list: Optional[List[AmbiguityItem]] = Field(None, alias='ambiguityList')
    # 语义理解的信息，语义搜图（searchType=SemanticImage）与图文搜人（searchType=SemanticImagePerson）首页会返回
    semantic_info: Optional[str] = Field(None, alias='semanticInfo')
    # 供用户选择/确认的人脸列表（face/recognize 歧义时返回）
    select_face_list: Optional[List[SelectFaceItem]] = Field(None, alias='selectFaceList')
    # 人脸图片理解结果（face/recognize 无歧义时返回，供 merge/image skipMultimodal=true 回传）
    recognize_face_info: Optional[RecognizeFaceInfo] = Field(None, alias='recognizeFaceInfo')


# ──────────────────────────── API 子类 ────────────────────────────


@search_fusion_api_registry.register('search_merge_image')
class MergeImageSearchApi(BaseSyncApi):
    """同步接口：个人云图片类整合搜索。"""

    PATH = '/richlifeApp/aiService/api/text/intelligent/search/merge/image'
    TIMEOUT = ApiTimeoutSettings.SEARCH_MERGE_IMAGE_SEC
    api_category = 'search'
    api_label = '个人云图片类整合搜索'
    # 业务码兜底重试：只读幂等查询，命中清单错误码时同参重发 1 次（默认空集=休眠）
    BUSINESS_CODE_RETRY_ENABLED = True

    def _build_result_dict(
        self, response: MergeImageSearchResponse, *args: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        """日志脱敏：移除 thumbnailUrl/contentHash/contentHashAlgorithm，
        截断 aiAnalysisInfo.content 到前 10 字符。详见 ``_redact.redact_search_result``。"""
        return redact_search_result(response.raw)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> MergeImageSearchResponse:
        strip_keywords_tag(raw)
        return MergeImageSearchResponse.from_response(raw, trace_id)

    def execute(
        self,
        request: MergeImageSearchRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> MergeImageSearchResponse:
        """透传 searchType 给 ``_build_result``。

        本类服务 4 种 searchType（语义搜图/图文搜人/个人云搜图/动态搜图），
        ``aiAnalysisInfo.score`` 的默认值口径随 searchType 不同，而
        ``_build_result`` 签名拿不到 request，经 kwargs 逐调用透传。
        """
        kwargs.setdefault(
            '_search_type',
            request.search_param.search_type if request.search_param else None,
        )
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _build_result(
        self,
        response: MergeImageSearchResponse,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        _search_type: Optional[str] = None,
        **kwargs: Any,
    ) -> MergeImageSearchResponse:
        """image 类 File 缺 ``aiAnalysisInfo.score`` 时按 searchType 补默认值。

        语义搜图（SemanticImage）/图文搜人（SemanticImagePerson）补 0；
        个人云搜图（ImageFile）/动态搜图（ImageDynamic）及兜底补 1。
        """
        default_score = 0.0 if _search_type in _SEMANTIC_SEARCH_TYPES else 1.0
        apply_ai_score_defaults(response.file_list, default_score)
        return response
