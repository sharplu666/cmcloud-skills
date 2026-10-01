#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提交图片整理任务（multipart/form-data，同步返回 taskId）。

接口文档：``dev/docs/api/organize/organize.md`` 4.2「提交图片整理任务」。

本接口与同类目下 ``query_photo_organize_task`` 配套使用：调用方先调本接口拿到
``taskId``，再按自身节奏轮询 query 接口直到 ``taskInfo.status ∈ {3, 4, 5}``。

设计要点：
  - **multipart/form-data**：上传 JSONL 文件（≤10M），走 ``api/base/_http.py`` 的
    ``post_multipart_with_retry``（第二个 multipart 接口出现后已从本模块上浮）。
  - **直接继承 ``BaseModel``**：``SyncRequest`` 的 ``sendType`` / ``fileUrl`` 等通用
    字段与本接口无关，参考 ``BatchMoveFilesRequest`` 的做法避免引入无关字段。
  - 响应解析仍走 ``BaseSyncApi._parse_response`` / ``_build_result``，复用基类终态
    日志与脱敏钩子。
"""

from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api.base.base_sync_api import BaseSyncApi, SyncResponse
from mclaw.api.base._http import post_multipart_with_retry
from mclaw.api.operation import operation_api_registry
from mclaw.api.operation._get_auth import get_photo_organize_header
from mclaw.api.operation._openclaw_context import resolve_openclaw_id
from mclaw.api.operation.photo_organize_query_api import (
    PhotoOrganizeTaskInfo,
    PhotoOrganizeTaskResult,
)
from mclaw.utils.settings import ApiTimeoutSettings

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger, status_log
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.operation')

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)


__all__ = [
    'PHOTO_ORGANIZE_FILE_MAX_BYTES',
    'PhotoOrganizeSubmitRequest',
    'PhotoOrganizeSubmitResponse',
    'PhotoOrganizeSubmitApi',
]

# 与接口文档「JSONL 文件 ≤10MB」一致
PHOTO_ORGANIZE_FILE_MAX_BYTES = 10 * 1024 * 1024
PROCESSING_HINT_MAX_LENGTH = 250


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class PhotoOrganizeSubmitRequest(BaseModel):
    """提交图片整理任务的入参（multipart 表单字段 + JSONL 文件内容）。

    字段对齐接口文档「提交图片整理任务」：
      - ``type``: 任务类型 1-归档 / 2-相册 / 3-故事
      - ``openclaw_id``: 能力/应用标识
      - ``session_id``: 会话 ID（归档目标会话，如 ``main``）
      - ``file``: JSONL 文件（≤10MB），每行一条记录

    ``file_name`` 与 ``file_content`` 不进 multipart 表单的普通字段区，而是组合成
    ``files=[('file', (file_name, file_content, 'application/octet-stream'))]`` 传给
    requests；其余字段进 ``data`` 区。``type`` 是 Python 内置，故 Python 字段名用
    ``type_`` + ``alias='type'``，``populate_by_name=True`` 让 ``type_=1`` 与
    ``type=1`` 两种构造方式都生效。

    JSONL 内容支持 str 或 bytes；str 内部按 utf-8 编码。
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra='forbid',
    )

    type_: int = Field(..., alias='type')
    openclaw_id: Optional[str] = Field(None, alias='openclawId')
    session_id: str = Field(..., alias='sessionId', description='会话 ID（归档目标会话，如 "main"）')
    process_hint: Optional[str] = Field(
        None,
        alias='processingHint',
        max_length=PROCESSING_HINT_MAX_LENGTH,
        description='处理中提示语，由大模型结合整理方案生成',
    )
    file_name: str = Field(..., description='JSONL 文件名，如 "cluster.jsonl"')
    file_content: Union[str, bytes] = Field(..., description='JSONL 文件内容（每行一条记录）')

    @field_validator('process_hint', mode='before')
    @classmethod
    def _truncate_process_hint(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text[:PROCESSING_HINT_MAX_LENGTH]

    def to_form(self) -> Tuple[Dict[str, Any], List[Tuple[str, Tuple[str, Any, str]]]]:
        """构造 multipart 表单的 ``(data, files)`` 两元组。"""
        openclaw_id = resolve_openclaw_id(self.openclaw_id)
        data: Dict[str, Any] = {
            'type': str(self.type_),
            'openclawId': openclaw_id,
            'sessionId': self.session_id,
        }
        process_hint = self._normalized_process_hint()
        if process_hint:
            data['processingHint'] = process_hint

        content: bytes = (
            self.file_content.encode('utf-8')
            if isinstance(self.file_content, str)
            else self.file_content
        )
        files: List[Tuple[str, Tuple[str, Any, str]]] = [
            ('file', (self.file_name, content, 'application/octet-stream')),
        ]
        return data, files

    def to_log_dict(self) -> Dict[str, Any]:
        """返回脱敏后的字典，仅用于 HTTP 日志展示（不含 file 正文）。"""
        try:
            openclaw_id = resolve_openclaw_id(self.openclaw_id)
        except ValueError:
            openclaw_id = self.openclaw_id or ''
        return {
            'type': self.type_,
            'openclawId': openclaw_id,
            'sessionId': self.session_id,
            'processingHint': self._normalized_process_hint(),
            'fileName': self.file_name,
            'fileSize': self._file_size_bytes(),
        }

    def _file_content_bytes(self) -> bytes:
        if isinstance(self.file_content, str):
            return self.file_content.encode('utf-8')
        return self.file_content

    def _file_size_bytes(self) -> int:
        return len(self._file_content_bytes())

    def to_request_payload_dict(
        self,
        *,
        max_file_bytes: int = PHOTO_ORGANIZE_FILE_MAX_BYTES,
    ) -> Dict[str, Any]:
        """返回与 multipart 提交一致的入参摘要（``type`` / ``openclawId`` / ``file``）。"""
        try:
            openclaw_id = resolve_openclaw_id(self.openclaw_id)
        except ValueError:
            openclaw_id = self.openclaw_id or ''
        content_bytes = self._file_content_bytes()
        payload: Dict[str, Any] = {
            'type': self.type_,
            'openclawId': openclaw_id,
            'sessionId': self.session_id,
            'file': content_bytes.decode('utf-8', errors='replace'),
        }
        process_hint = self._normalized_process_hint()
        if process_hint:
            payload['processingHint'] = process_hint
        if len(content_bytes) > max_file_bytes:
            payload['file'] = content_bytes[:max_file_bytes].decode('utf-8', errors='replace')
            payload['fileTruncated'] = True
        return payload

    def _normalized_process_hint(self) -> str:
        return str(self.process_hint or '').strip()


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class PhotoOrganizeSubmitResponse(SyncResponse):
    """提交图片整理任务的响应。

    服务端返回 ``{success, code, message, data: {taskId, taskInfo?, results?}}``。
    ``SyncResponse.from_response`` 会自动展平 ``data`` 嵌套层；任务较小时，服务端可能
    在 submit 阶段直接同步返回 ``taskInfo`` 与 ``results``，字段结构与 query 接口一致。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_id: str = Field('', alias='taskId')
    task_info: Optional[PhotoOrganizeTaskInfo] = Field(None, alias='taskInfo')
    results: List[PhotoOrganizeTaskResult] = Field(default_factory=list)


# ──────────────────────────── API 类 ────────────────────────────


@operation_api_registry.register('submit_photo_organize_task')
class PhotoOrganizeSubmitApi(BaseSyncApi):
    """提交图片整理任务（multipart/form-data）。

    重写 ``execute`` 以走 multipart 路径；响应解析仍走基类 ``_parse_response`` →
    ``_build_result``，复用终态日志、脱敏、重试等基础设施。

    鉴权头见 ``get_photo_organize_header(multipart=True)``（含 ``x-yun-client-info``；
    multipart 不设 ``Content-Type``）。
    """

    PATH = '/richlifeApp/api/openclaw/photoOrganize/task'
    # multipart 文件上传耗时高于 JSON，放大默认超时
    TIMEOUT = ApiTimeoutSettings.PHOTO_ORGANIZE_SUBMIT_SEC

    api_category = 'operation'
    api_label = '提交图片整理任务'

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = lambda: get_photo_organize_header(multipart=True)

    def execute(
        self,
        request: PhotoOrganizeSubmitRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PhotoOrganizeSubmitResponse:
        """发起一次 multipart 提交，返回包含 ``taskId`` 的响应。"""
        url = self._resolve_url(self.PATH)
        data, files = request.to_form()
        extra_info = info_dict if isinstance(info_dict, dict) else {}
        log_data = request.to_log_dict()

        try:
            raw, trace_id = post_multipart_with_retry(
                url,
                data,
                files,
                auth_fn=self._auth,
                timeout=kwargs.get('timeout', self.TIMEOUT),
                max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
                retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
                logger=self.logger,
                log_payload=log_data,
            )
            response = self._parse_response(raw, trace_id, *args, **kwargs)
            msg = self._format_result_msg(response, url, 'execute', *args, **kwargs)
        except Exception:
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[{type(self).__name__}] parse/format FAILED. data={log_data}. exc={flat_exc}',
                logger=self.logger,
                info_dict={'api': type(self).__name__, **extra_info},
                server_type='SYNC',
                stdout=True,
            )
            raise

        status_log(
            msg=msg,
            logger=self.logger,
            info_dict={'api': type(self).__name__, 'trace_id': trace_id, **extra_info},
            server_type='SYNC',
        )
        return self._build_result(response, raw, trace_id, *args, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> PhotoOrganizeSubmitResponse:
        """类型化响应解析：返回 ``PhotoOrganizeSubmitResponse``。"""
        return PhotoOrganizeSubmitResponse.from_response(raw, trace_id)
