#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""face/recognize 第一跳：多模态理解参考图 + 歧义判定（无分页、无状态）。

接口复用 merge/image 的请求/响应模型（公共库 ``FaceRecognizeApi``）；
searchType=SemanticImagePerson 必须严格配 searchImagePersonParam（错配后端报
01000001，docs/business_logic.md §2.6 戒律）。网络/超时错误由公共库抛
RuntimeError 原样上抛（cli 异常梯转「服务端错误」回执，勿自动重试）；
业务码 10000041（未检测到人脸）= 正常零命中终态（``PersonNoTargetStop``）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mclaw.api.search_fusion.search_merge_image_api import (
    MergeImageSearchParam,
    MergeImageSearchRequest,
    MergeImageSearchResponse,
)
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher

from services.search.errors import SearchServiceError

#: 接口业务错误码 → 用户友好提示（命中时不再透传原始 message）
ERROR_CODE_MESSAGES = {
    '10000031': '图片异常，建议更换更清晰的参考图',  # 文件中图片或图片像素异常
}

#: 未检出目标人脸的业务码（图片未检测到人脸）——正常现象，按零命中收束非报错
PERSON_NO_TARGET_CODE = '10000041'


class PersonNoTargetStop(Exception):
    """未检出目标人脸终态信号（业务码 10000041 / recognizeFaceInfo 空壳）。

    正常现象而非错误：与语义搜图命中 0 同口径，由 cli 捕获后发零命中 searchResults
    回执（exit 0）。有意不继承 RuntimeError（避开 cli 异常梯的 RuntimeError 档，
    同 ``PersonAmbiguityStop`` 手法）。
    """


def call_face_recognize(text: str, file_ids: List[str]) -> MergeImageSearchResponse:
    """发起 face/recognize（只做多模态理解 + 人脸判定，不带 pageInfo）。

    ``text`` 原样进请求 wire 键 ``text``（首搜为 flow 组装的 JSON
    ``{"user_query", "bindings":[{"fileId","msg"}]}``，fileId=真实 fileId）。
    """
    request = MergeImageSearchRequest(
        search_param=MergeImageSearchParam.model_validate({
            'searchType': 'SemanticImagePerson',
            'searchImagePersonParam': {
                'text': text,
                'fileIdList': [str(fid).strip() for fid in file_ids],
            },
        })
    )
    return get_cloud_dispatcher().search_fusion.search_face_recognize(request)


def check_person_response_success(resp: Any) -> None:
    """person 系响应业务失败转 ``SearchServiceError``（友好码优先，含 traceId）。

    10000041（未检测到人脸）例外：转 ``PersonNoTargetStop`` 按零命中收束。
    """
    if getattr(resp, 'success', False):
        return
    code = str(getattr(resp, 'code', '') or '')
    if code == PERSON_NO_TARGET_CODE:
        raise PersonNoTargetStop()
    message = str(getattr(resp, 'message', '') or '').strip() or '查询失败'
    trace_id = str(getattr(resp, 'trace_id', '') or '').strip()
    trace_part = f'（traceId={trace_id}）' if trace_id else ''
    friendly = ERROR_CODE_MESSAGES.get(code)
    if friendly:
        raise SearchServiceError(f'{friendly}{trace_part}')
    raise SearchServiceError(
        f'图文搜人失败 [{code}]：{message}{trace_part}；请停止并交用户决策，勿自动重试'
    )


def response_requires_select_face(resp: Any) -> bool:
    """歧义判定：顶层 ambiguityFlag=true 或 ambiguityList 非空即需用户选脸。"""
    top_flag = getattr(resp, 'ambiguity_flag', None)
    if isinstance(top_flag, bool) and top_flag:
        return True
    return bool(getattr(resp, 'ambiguity_list', None) or [])


def is_empty_recognize_shell(rfi: Optional[Any]) -> bool:
    """recognizeFaceInfo 空壳判定（selectFaceList 与 rewriteQuery 均空）。

    空壳禁止回传 merge/image（会被判参数错误），调用方须前置拦截转友好报错。
    """
    if rfi is None:
        return False
    return not rfi.select_face_list and not str(rfi.rewrite_query or '').strip()


def serialize_recognize_face_info(rfi: Any) -> Dict[str, Any]:
    """recognizeFaceInfo → camelCase dict（二跳请求与 header 参数快照共用同一形态）。"""
    return rfi.model_dump(by_alias=True, exclude_none=True)


__all__ = [
    'ERROR_CODE_MESSAGES',
    'PERSON_NO_TARGET_CODE',
    'PersonNoTargetStop',
    'call_face_recognize',
    'check_person_response_success',
    'is_empty_recognize_shell',
    'response_requires_select_face',
    'serialize_recognize_face_info',
]
