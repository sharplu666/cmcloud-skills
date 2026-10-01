#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云图片类整合AI信息接口（Pydantic v2）。

按图片文件 fileId 列表批量获取底座文件详情，并补齐 ``aiAnalysisInfo``（AI 分析
结果）返回。File 结构与 ``search_merge_image_api``（个人云图片类整合搜索）一致。

接口路径：POST /richlifeApp/aiService/api/text/intelligent/search/merge/image/aiAnalysisInfo
同步返回结果（无 taskId、无轮询）。

接口已上线（2026-09-18 真实链路实测联通），默认走真实请求。联调期可经
``SearchByFileIdApi.MOCK_ENABLED = True`` 或按调用传 ``mock_enabled=True``
切回内置 mock（逐条 fileId 生成一份结构完整的 File），无需改业务代码。

出参比对：``_build_result`` 对输入 fileList 与输出 fileList 的 fileId 做集合比对，
缺失项通过 ``status_log`` + ``openclaw_logger`` 双写日志（info_dict 带 traceId）；
无缺失不打印。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.search_fusion import search_fusion_api_registry
from mclaw.api.search_fusion._models import File, apply_ai_score_defaults
from mclaw.api.search_fusion._redact import redact_search_result
from mclaw.utils.logger import openclaw_logger, status_log
from mclaw.utils.settings import ApiTimeoutSettings

__all__ = [
    'SearchByFileIdRequest',
    'SearchByFileIdResponse',
    'SearchByFileIdApi',
]


# ──────────────────────────── Request / Response ────────────────────────────


class SearchByFileIdRequest(SyncRequest):
    """入参：fileList —— 文件 Id 列表（必填，最大 500 条）。

    父类通用媒体字段（sendType/fileUrl/fileId/imageExt/sourceTaskId）对本接口
    无意义，``to_payload`` 只输出 ``fileList``。
    """

    file_list: List[str] = Field(default_factory=list, alias='fileList')

    def to_payload(self) -> Dict[str, Any]:
        return {'fileList': list(self.file_list)}


class SearchByFileIdResponse(SyncResponse):
    """出参：fileList —— 文件信息列表（File 结构与 merge/image 一致）。

    基类 ``SyncResponse.from_response`` 默认展平 data 嵌套层，``fileList``
    自动填充，无需重写 ``from_response``。
    """

    file_list: List[File] = Field(default_factory=list, alias='fileList')

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = '', request_file_list: Optional[List[str]] = None
    ) -> 'SearchByFileIdResponse':
        instance = super().from_response(raw, trace_id)
        # 请求侧 fileId 列表挂上实例，供 _build_result 做输入/输出比对
        object.__setattr__(instance, '_request_file_list', list(request_file_list or []))
        return instance


# ──────────────────────────── Mock（联调期可选） ────────────────────────────


def _build_mock_raw(file_ids: List[str]) -> Dict[str, Any]:
    """按入参 fileId 列表逐条生成结构完整的 File mock（服务端响应包壳）。

    字段对齐 ``search_merge_image_api`` 返回的 File 结构（含 aiAnalysisInfo），
    供联调期调用方走通完整解析链路；字段值均为占位，不代表真实业务数据。
    """
    file_list: List[Dict[str, Any]] = []
    for index, file_id in enumerate(file_ids, start=1):
        file_list.append({
            'fileId': file_id,
            'parentFileId': 'mockParentFileId',
            'name': f'mock_{index}.jpg',
            'type': 'file',
            'category': 'image',
            'createdAt': '2026-01-01 00:00:00',
            'updatedAt': '2026-01-01 00:00:00',
            'size': 1024,
            'fileExtension': 'jpg',
            'thumbnailUrl': f'https://mock.example.com/thumbnail/{file_id}',
            'contentHash': f'mockhash{index}',
            'contentHashAlgorithm': 'SHA-256',
            'mediaMetaInfo': {
                'width': 1920,
                'height': 1080,
                'takenAt': '2026-01-01 00:00:00',
            },
            'thumbnailUrls': [
                {'style': 'Small', 'url': f'https://mock.example.com/thumbnail/{file_id}/s'},
                {'style': 'Middle', 'url': f'https://mock.example.com/thumbnail/{file_id}/m'},
                {'style': 'Big', 'url': f'https://mock.example.com/thumbnail/{file_id}/b'},
            ],
            'aiAnalysisInfo': {
                'faceInfoList': [],
                'thingLabelList': [{'name': 'mock标签', 'score': 0.9}],
                'imageQuality': {'imgQuality': 0.8},
                'score': 0.0,
                'peopleNameList': [],
                'relationshipNameList': [],
                'content': f'mock AI 分析内容 {index}',
                'objectList': [],
                'imgOCRContent': '',
            },
        })
    return {
        'success': True,
        'code': '0000',
        'message': 'success',
        'data': {'fileList': file_list},
    }


# ──────────────────────────── API 子类 ────────────────────────────


@search_fusion_api_registry.register('search_by_fileId')
class SearchByFileIdApi(BaseSyncApi):
    """同步接口：个人云图片类整合AI信息（按 fileId 列表批量取文件详情 + AI 分析）。"""

    PATH = '/richlifeApp/aiService/api/text/intelligent/search/merge/image/aiAnalysisInfo'
    TIMEOUT = ApiTimeoutSettings.SEARCH_BY_FILE_ID_SEC
    api_category = 'search'
    api_label = '个人云图片类整合AI信息'

    #: 接口已上线：默认走真实请求；联调期可置 True（或按调用传
    #: ``mock_enabled=True``）短路 HTTP 走内置 mock。
    MOCK_ENABLED = False

    def execute(
        self,
        request: SearchByFileIdRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SearchByFileIdResponse:
        """mock 开关开启时短路 HTTP，本地构造响应；否则走基类真实请求。"""
        mock_enabled = kwargs.pop('mock_enabled', self.MOCK_ENABLED)
        if mock_enabled:
            return self._execute_mock(request, info_dict=info_dict)
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _execute_mock(
        self,
        request: SearchByFileIdRequest,
        info_dict: Optional[Dict[str, Any]] = None,
    ) -> SearchByFileIdResponse:
        """mock 执行：本地生成 raw → 解析 → 终态日志 → fileId 比对，链路与真实请求一致。"""
        trace_id = uuid.uuid4().hex
        raw = _build_mock_raw(request.file_list)
        response = SearchByFileIdResponse.from_response(
            raw, trace_id, request_file_list=request.file_list
        )
        extra_info = info_dict if isinstance(info_dict, dict) else {}
        status_log(
            msg=f'[{type(self).__name__}] mock execute {self.PATH} success. '
            f'fileCount={len(response.file_list)}',
            logger=self.logger,
            info_dict={'api': type(self).__name__, 'traceId': trace_id, **extra_info},
            server_type='SYNC',
        )
        return self._build_result(response, raw, trace_id)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> SearchByFileIdResponse:
        return SearchByFileIdResponse.from_response(
            raw, trace_id, request_file_list=kwargs.get('_request_file_list')
        )

    def _build_result_dict(
        self, response: SearchByFileIdResponse, *args: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        """日志脱敏：与 merge/image 一致，详见 ``_redact.redact_search_result``。"""
        return redact_search_result(response.raw)

    def _build_result(
        self,
        response: SearchByFileIdResponse,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> SearchByFileIdResponse:
        """比对输入/输出 fileId：缺失项双写 status_log + openclaw_logger；无缺失不打印。

        同时按本接口口径（非语义搜索）为 image 类 File 缺 ``aiAnalysisInfo.score``
        时补默认值 1，与 merge/image 的 ImageFile 分支对齐。
        """
        requested = set(getattr(response, '_request_file_list', None) or [])
        returned = {f.file_id for f in response.file_list if f.file_id}
        lost = sorted(requested - returned)
        if lost:
            msg = f'输出丢失的fileId是: {lost}'
            info = {'api': type(self).__name__, 'traceId': trace_id}
            status_log(msg=msg, logger=self.logger, info_dict=info, server_type='SYNC')
            openclaw_logger.warning(
                'SYNC|||%s|%s', msg, ''.join(f'{k}:{v}|' for k, v in info.items())
            )
        apply_ai_score_defaults(response.file_list, 1.0)
        return response
