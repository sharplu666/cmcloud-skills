#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人脸识别接口（Pydantic v2）。

上传参考图 fileId 列表，调用多模态大模型识别人脸：
  - 有歧义：返回 ambiguityList / selectFaceList 供前端展示选脸卡片；
  - 无歧义：返回 recognizeFaceInfo（rewriteQuery + 筛选后的人脸列表），
    供后续调用 ``merge/image``（skipMultimodal=true）继续搜索。

接口路径：POST /richlifeApp/api/text/intelligent/search/face/recognize
同步返回结果（无 taskId、无轮询）。

入参/出参与 ``search_merge_image_api`` 同构（searchParam 嵌套结构 +
fileList/totalCount/pageAfter/ambiguityList/semanticInfo/selectFaceList/
recognizeFaceInfo），故直接复用其 Request/Response，本文件只定义 Api 子类。
"""

from __future__ import annotations

from typing import Any, Dict

from mclaw.api import BaseSyncApi
from mclaw.api.search_fusion import search_fusion_api_registry
from mclaw.utils.settings import ApiTimeoutSettings
from mclaw.api.search_fusion._redact import redact_search_result, strip_keywords_tag
from mclaw.api.search_fusion.search_merge_image_api import (
    MergeImageSearchRequest,
    MergeImageSearchResponse,
)
from mclaw.api.search_fusion._models import apply_ai_score_defaults


__all__ = ['FaceRecognizeApi']


@search_fusion_api_registry.register('search_face_recognize')
class FaceRecognizeApi(BaseSyncApi):
    """同步接口：人脸识别（多模态理解 + 人脸判定）。"""

    PATH = '/richlifeApp/api/text/intelligent/search/face/recognize'
    TIMEOUT = ApiTimeoutSettings.SEARCH_MERGE_IMAGE_SEC
    api_category = 'search'
    api_label = '人脸识别'
    # 业务码兜底重试：只读幂等查询，命中清单错误码时同参重发 1 次（默认空集=休眠）
    BUSINESS_CODE_RETRY_ENABLED = True

    def _build_result_dict(
        self, response: MergeImageSearchResponse, *args: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        """日志脱敏：与 merge/image 一致，详见 ``_redact.redact_search_result``。"""
        return redact_search_result(response.raw)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> MergeImageSearchResponse:
        strip_keywords_tag(raw)
        return MergeImageSearchResponse.from_response(raw, trace_id)

    def _build_result(
        self,
        response: MergeImageSearchResponse,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> MergeImageSearchResponse:
        """图文搜人：image 类 File 缺 ``aiAnalysisInfo.score`` 时补 0（fill-if-missing）。"""
        apply_ai_score_defaults(response.file_list, 0.0)
        return response
