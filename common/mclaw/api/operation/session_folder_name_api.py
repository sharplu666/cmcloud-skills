#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询/生成会话文件夹名称（同步接口）。

接口路径：POST /richlifeApp/api/openclaw/session/folder/name

服务端按 sessionId 查映射表：命中返回已有文件夹，未命中则按规则生成
``folderName``；当 ``enableAutoCreateDir=true``（默认）时一并创建个人云文件夹，
``false`` 时只返回目录名称不创建。异常时降级返回原始 ``sessionId``
（``folderId`` 为空），调用方据此判断是否走兜底链路。

入参（``SessionFolderNameRequest``）：
  | 字段 | 必填 | 说明 |
  | sessionId | M | 会话 ID |
  | openclawId | M | OpenClaw 实例 ID |
  | sessionType | O | chat=普通对话（默认）/ cron=定时任务 |
  | jobName | O | sessionType=cron 时必填 |
  | enableAutoCreateDir | O | true=返回目录名称同时创建目录（默认）/ false=仅返回目录名称，不创建 |

出参（``SessionFolderNameResponse``）：
  | 字段 | 必填 | 说明 |
  | folderName | M | 文件夹名称；异常降级时为原始 sessionId |
  | folderId | M | 个人云文件夹 ID；异常降级时为空串 |
  | namePath | O | 服务端返回的文件全路径（当前未返回，预留） |
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.operation import operation_api_registry


__all__ = [
    'SessionFolderNameRequest',
    'SessionFolderNameResponse',
    'SessionFolderNameApi',
]


class SessionFolderNameRequest(BaseModel):
    """入参：sessionId / openclawId / sessionType / jobName / enableAutoCreateDir。

    本接口无 sendType/fileUrl 等媒体字段，故直接继承 ``BaseModel``
    （与 ``PhotoOrganizeQueryRequest`` 一致），不走 ``SyncRequest``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    session_id: str = Field(..., alias='sessionId')
    openclaw_id: str = Field(..., alias='openclawId')
    session_type: str = Field('chat', alias='sessionType')
    job_name: Optional[str] = Field(None, alias='jobName')
    # enableAutoCreateDir：true 返回目录名同时创建目录（默认）；false 仅返回目录名、不创建
    enable_auto_create_dir: bool = Field(True, alias='enableAutoCreateDir')

    def to_payload(self) -> Dict[str, Any]:
        # job_name=None 时 exclude_none 自动剔除；cron 场景设值后纳入；
        # enable_auto_create_dir 为 bool 非空，恒随请求上送
        return self.model_dump(by_alias=True, exclude_none=True)


class SessionFolderNameResponse(SyncResponse):
    """出参：folderName / folderId / namePath。

    响应为标准信封 ``{success, code:'0000', message, data:{...}}``，业务字段
    直接落在 ``data`` 下，故无需重写 ``from_response`` —— 基类展平 ``data``
    后靠 alias 自动填充。``namePath`` 当前服务端未返回，作为可选字段预留，
    ``extra='ignore'`` 兼容其缺失。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    folder_name: str = Field('', alias='folderName')
    folder_id: str = Field('', alias='folderId')
    name_path: str = Field('', alias='namePath')


@operation_api_registry.register('resolve_session_folder_name')
class SessionFolderNameApi(BaseSyncApi):
    """同步接口：查询/生成会话文件夹名称。"""

    PATH = '/richlifeApp/api/openclaw/session/folder/name'
    api_category = 'operation'
    api_label = '查询/生成会话文件夹名称'

    def execute(
        self,
        request: SessionFolderNameRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SessionFolderNameResponse:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> SessionFolderNameResponse:
        return SessionFolderNameResponse.from_response(raw, trace_id)
