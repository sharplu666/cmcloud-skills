#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询异步任务执行状态（Pydantic v2）。

查询异步任务（如批量移动）的执行状态和结果，可独立查询任意 taskId 的进度。

接口路径：POST /richlifeApp/personalSaas/task/get
同步返回结果（无 taskId、无轮询）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.search import search_api_registry


__all__ = [
    'TaskInfo',
    'BatchFileResult',
    'GetAsyncTaskStatusRequest',
    'GetAsyncTaskStatusResponse',
    'GetAsyncTaskStatusApi',
]


# ──────────────────────────── 出参子结构 ────────────────────────────


class TaskInfo(BaseModel):
    """异步任务信息。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    status: Optional[str] = Field(None, alias='status')
    progress: Optional[Any] = Field(None, alias='progress')
    task_type: Optional[str] = Field(None, alias='taskType')
    code: Optional[str] = Field(None, alias='code')

    @field_validator('task_type', mode='before')
    @classmethod
    def _coerce_task_type(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class BatchFileResult(BaseModel):
    """批量文件单条处理结果。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    err_code: Optional[str] = Field(None, alias='errCode')
    message: Optional[str] = Field(None, alias='message')
    src_file: Optional[Dict[str, Any]] = Field(None, alias='srcFile')


# ──────────────────────────── Request / Response ────────────────────────────


class GetAsyncTaskStatusRequest(SyncRequest):
    """入参：仅 taskId。

    父类通用字段（sendType/fileUrl/...）对本接口无意义，to_payload 完整重写，
    只输出 taskId。
    """

    task_id: str = Field(..., alias='taskId')

    def to_payload(self) -> Dict[str, Any]:
        return {'taskId': self.task_id}


class GetAsyncTaskStatusResponse(SyncResponse):
    """出参：taskInfo + batchFileResults。

    基类 SyncResponse.from_response 已默认展平 data 嵌套层，
    taskInfo/batchFileResults 会被自动填充，无需重写 from_response。
    """

    task_info: Optional[TaskInfo] = Field(None, alias='taskInfo')
    batch_file_results: List[BatchFileResult] = Field(
        default_factory=list, alias='batchFileResults'
    )


# ──────────────────────────── API 子类 ────────────────────────────


@search_api_registry.register('get_async_task_status')
class GetAsyncTaskStatusApi(BaseSyncApi):
    """同步接口：查询异步任务执行状态。"""

    PATH = '/richlifeApp/personalSaas/task/get'
    api_category = 'search'
    api_label = '查询异步任务状态'

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> GetAsyncTaskStatusResponse:
        return GetAsyncTaskStatusResponse.from_response(raw, trace_id)
