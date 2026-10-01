#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询图片整理任务结果（application/json，同步）。

接口文档：``dev/docs/api/organize/organize.md`` 4.2「查询图片整理任务结果」。

与同包下 ``photo_organize_submit_api`` 配套：调用方提交任务拿到 ``taskId`` 后，
按自身节奏轮询本接口直到 ``task_info.status ∈ {3, 4, 5}``（3-成功 / 4-失败 /
5-部分成功）。终态时 ``results`` 可能包含每条记录的处理结果。

完全走 ``BaseSyncApi.execute`` 标准流程（JSON POST → 展平 ``data`` → 嵌套模型
自动填充）；无需重写 ``execute``。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api.base.base_sync_api import BaseSyncApi, SyncResponse
from mclaw.api.operation import operation_api_registry
from mclaw.api.operation._get_auth import get_photo_organize_header
from mclaw.api.operation._openclaw_context import resolve_openclaw_id
from mclaw.utils.settings import ApiTimeoutSettings


__all__ = [
    'PhotoOrganizeTaskInfo',
    'PhotoOrganizeTaskResult',
    'PhotoOrganizeQueryRequest',
    'PhotoOrganizeQueryResponse',
    'PhotoOrganizeQueryApi',
]


# ──────────────────────────── 嵌套子模型 ────────────────────────────


class PhotoOrganizeTaskInfo(BaseModel):
    """任务主信息（响应 ``data.taskInfo``）。

    字段对齐接口文档 4.2「TaskInfo」。``status``：1-待处理 / 2-处理中 /
    3-全部成功 / 4-全部失败 / 5-部分成功；``task_type``：1-归档 / 2-相簿 / 3-回忆故事。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_id: str = Field('', alias='taskId')
    task_type: int = Field(0, alias='taskType')
    status: int = 0
    total_count: int = Field(0, alias='totalCount')
    success_count: int = Field(0, alias='successCount')
    fail_count: int = Field(0, alias='failCount')
    error_code: Optional[str] = Field(None, alias='errorCode')
    error_msg: Optional[str] = Field(None, alias='errorMsg')
    processing_hint: Optional[str] = Field(None, alias='processingHint')
    finish_content: Optional[str] = Field(None, alias='finishContent')
    created_at: str = Field('', alias='createdAt')
    started_at: Optional[str] = Field(None, alias='startedAt')
    finished_at: Optional[str] = Field(None, alias='finishedAt')

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（3-成功 / 4-失败 / 5-部分成功）。"""
        return self.status in (3, 4, 5)

    @property
    def is_success(self) -> bool:
        """是否成功（status == 3）。"""
        return self.status == 3


class PhotoOrganizeTaskResult(BaseModel):
    """任务明细结果项（响应 ``data.results[*]``）。

    按 ``taskType`` 返回不同含义：``Id`` 为目录 id / 相册 id / 故事 id；
    ``Name`` 为对应名称。两字段在中间态/失败时可能为空。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_type: int = Field(0, alias='taskType')
    id: Optional[str] = Field(None, alias='Id')
    name: Optional[str] = Field(None, alias='Name')


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class PhotoOrganizeQueryRequest(BaseModel):
    """查询图片整理任务的入参。

    字段对齐接口文档「查询图片整理任务结果」：``taskId``、``openclawId`` 必填。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    task_id: str = Field(..., alias='taskId')
    openclaw_id: Optional[str] = Field(None, alias='openclawId')

    def to_payload(self) -> Dict[str, Any]:
        """输出驼峰 JSON（过滤 None 字段）。"""
        return {
            'taskId': self.task_id,
            'openclawId': resolve_openclaw_id(self.openclaw_id),
        }


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class PhotoOrganizeQueryResponse(SyncResponse):
    """查询图片整理任务的响应。

    服务端响应 ``{success, code, message, data: {taskInfo, results}}``。
    基类 ``SyncResponse.from_response`` 会展平 ``data`` 嵌套层，``task_info``
    与 ``results`` 经 ``alias`` 自动填充——**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_info: Optional[PhotoOrganizeTaskInfo] = Field(None, alias='taskInfo')
    results: List[PhotoOrganizeTaskResult] = Field(default_factory=list)


# ──────────────────────────── API 类 ────────────────────────────


@operation_api_registry.register('query_photo_organize_task')
class PhotoOrganizeQueryApi(BaseSyncApi):
    """查询图片整理任务结果（JSON POST）。

    完全复用 ``BaseSyncApi.execute`` 标准流程，仅重写 ``_parse_response`` 指向
    本接口的响应子类。
    """

    PATH = '/richlifeApp/api/openclaw/photoOrganize/task/query'
    TIMEOUT = ApiTimeoutSettings.PHOTO_ORGANIZE_QUERY_SEC

    api_category = 'operation'
    api_label = '查询图片整理任务结果'

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_photo_organize_header

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> PhotoOrganizeQueryResponse:
        """类型化响应解析：返回 ``PhotoOrganizeQueryResponse``。"""
        return PhotoOrganizeQueryResponse.from_response(raw, trace_id)
