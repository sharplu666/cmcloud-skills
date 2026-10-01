#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片整理失败重试（application/json，同步）。

接口文档：``dev/docs/api/organize/retry.md``。

与同包下 ``photo_organize_submit`` / ``photo_organize_query`` 配套：当任务终态为
失败 (4) 或部分失败 (5) 时调用本接口重新发起处理，**仅处理失败文件**。响应结构
与 query 接口一致（``taskInfo`` + ``results``），但 ``taskInfo`` 字段集不同——
retry 额外含 ``sessionId`` / ``filterCount`` / ``createTime`` / ``startTime`` /
``finishTime``，``results`` 项含 ``successCount`` / ``failCount`` / ``filterCount``，
且 ``taskType`` 在文档中标记为 String。故本接口**单独定义** ``PhotoOrganizeRetryTaskInfo``
/ ``PhotoOrganizeRetryTaskResult``，不复用 query 的子模型（字段集不一致，符合
"每个接口定义自己的入参/出参 BaseModel" 规则）。

完全走 ``BaseSyncApi.execute`` 标准流程（JSON POST → 展平 ``data`` → 嵌套模型
自动填充）；仅需重写 ``_parse_response`` 指向本接口的 Response 子类。
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
    'PhotoOrganizeRetryTaskInfo',
    'PhotoOrganizeRetryTaskResult',
    'PhotoOrganizeRetryRequest',
    'PhotoOrganizeRetryResponse',
    'PhotoOrganizeRetryApi',
]


# ──────────────────────────── 嵌套子模型 ────────────────────────────


class PhotoOrganizeRetryTaskInfo(BaseModel):
    """重试任务主信息（响应 ``data.taskInfo``）。

    字段对齐接口文档 ``retry.md``「PhotoOrganizeTaskInfoVO」。
    ``status``：1-待处理 / 2-处理中 / 3-成功 / 4-失败 / 5-部分成功；
    ``task_type``：1-归档 / 2-相簿 / 3-回忆故事（int，如 ``1``；服务端实际返回 int，
    与 query 接口一致——接口文档 TaskInfoVO 表格标记为 String 但响应示例即为 int，TaskResultVO
    标记为 Integer）。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    # 必填字段（文档标记 M）：无默认值，服务端缺失即抛 ValidationError，避免静默用占位值。
    task_id: str = Field(..., alias='taskId')
    task_type: int = Field(..., alias='taskType')
    status: int = Field(...)
    total_count: int = Field(..., alias='totalCount')
    success_count: int = Field(..., alias='successCount')
    create_time: str = Field(..., alias='createTime')
    # 可选字段（文档标记 O）：缺省 None。
    session_id: Optional[str] = Field(None, alias='sessionId')
    fail_count: Optional[int] = Field(None, alias='failCount')
    filter_count: Optional[int] = Field(None, alias='filterCount')
    error_code: Optional[str] = Field(None, alias='errorCode')
    error_msg: Optional[str] = Field(None, alias='errorMsg')
    processing_hint: Optional[str] = Field(None, alias='processingHint')
    finish_content: Optional[str] = Field(None, alias='finishContent')
    # startTime/finishTime 文档标 M，但属状态相关字段：任务未开始/未结束时服务端会缺失，
    # 缺失是正常状态而非契约违规（文档类型标注已由 taskType str/int 证明不可靠），故按 Optional。
    start_time: Optional[str] = Field(None, alias='startTime')
    finish_time: Optional[str] = Field(None, alias='finishTime')

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（3-成功 / 4-失败 / 5-部分成功）。"""
        return self.status in (3, 4, 5)

    @property
    def is_success(self) -> bool:
        """是否成功（status == 3）。"""
        return self.status == 3


class PhotoOrganizeRetryTaskResult(BaseModel):
    """重试任务明细结果项（响应 ``data.results[*]``）。

    按 ``taskType`` 返回不同含义：``id`` 为个人云目录 Id / 相簿 ID / 回忆故事 ID；
    ``name`` 为对应名称。两字段在中间态/失败时可能为空。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    # taskType 必填（文档标记 M）；其余为可选（O），缺省 None。
    task_type: int = Field(..., alias='taskType')
    id: Optional[str] = None
    name: Optional[str] = None
    success_count: Optional[int] = Field(None, alias='successCount')
    fail_count: Optional[int] = Field(None, alias='failCount')
    filter_count: Optional[int] = Field(None, alias='filterCount')


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class PhotoOrganizeRetryRequest(BaseModel):
    """图片整理失败重试的入参。

    字段对齐接口文档 ``retry.md``：``openclawId``、``taskId`` 必填。
    用户 ID 由平台根据 accesstoken 自动解析填充，第三方调用方无需也不应传入。
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


class PhotoOrganizeRetryResponse(SyncResponse):
    """图片整理失败重试的响应。

    服务端响应 ``{success, code, message, data: {taskInfo, results}}``。
    基类 ``SyncResponse.from_response`` 会展平 ``data`` 嵌套层，``task_info``
    与 ``results`` 经 ``alias`` 自动填充——**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_info: Optional[PhotoOrganizeRetryTaskInfo] = Field(None, alias='taskInfo')
    results: List[PhotoOrganizeRetryTaskResult] = Field(default_factory=list)


# ──────────────────────────── API 类 ────────────────────────────


@operation_api_registry.register('retry_photo_organize_task')
class PhotoOrganizeRetryApi(BaseSyncApi):
    """图片整理失败重试（JSON POST）。

    当任务终态为失败 (4) 或部分失败 (5) 时调用，仅重新发起失败文件的处理。
    完全复用 ``BaseSyncApi.execute`` 标准流程，仅重写 ``_parse_response`` 指向
    本接口的响应子类。

    鉴权头复用 ``get_photo_organize_header``（含 ``x-yun-client-info``；
    JSON 请求自动设 ``Content-Type: application/json``）。
    """

    PATH = '/richlifeApp/api/openclaw/photoOrganize/task/retry'
    TIMEOUT = ApiTimeoutSettings.PHOTO_ORGANIZE_RETRY_SEC

    api_category = 'operation'
    api_label = '图片整理失败重试'

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
    ) -> PhotoOrganizeRetryResponse:
        """类型化响应解析：返回 ``PhotoOrganizeRetryResponse``。"""
        return PhotoOrganizeRetryResponse.from_response(raw, trace_id)
