#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量复制文件/文件夹（异步接口）。

提交路径：POST /richlifeApp/personalSaas/file/batchCopy
轮询路径：POST /richlifeApp/personalSaas/task/get

提交后返回 taskId，轮询 task/get 直到 ``taskInfo.status == 'Succeed'``。
单次最多 10000 个 fileId（同步版 batchCopySync 限 100，本封装为异步版）。

入参（``BatchCopyRequest``）：
  | 字段 | 必填 | 说明 |
  | fileIds | M | 文件 id 列表 |
  | toParentFileId | M | 目的父目录，根目录 ``'/'`` |
  | fileExtInfos | O | [{fileId, localOperatedAt?}] |
  | tagList | O | [{key, value}]，不可与 tagInfo 同用 |
  | toUserId | O | 扩展字段，特定业务场景透传 |

出参（提交）：``data.taskId``

出参（轮询 ``BatchCopyPollResponse``）：
  | 字段 | 说明 |
  | taskInfo | taskId / status / progress / taskType / code / message |
  | batchFileResults | FileResult[]：srcFile / rstFile / errCode / message |
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import AsyncPollResponse, BaseAsyncApi
from mclaw.api.base.base_async_api import AsyncSubmitResponse
from mclaw.api.base._http import post_json_with_retry
from mclaw.api.personal_saas import personal_saas_api_registry
from mclaw.utils.settings import ApiTimeoutSettings

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger, status_log
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.personal_saas')

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)


__all__ = [
    'BatchCopyRequest',
    'BatchCopyPollResponse',
    'BatchCopyApi',
]


class BatchCopyRequest(BaseModel):
    """批量复制提交入参（cloudId 体系，直接继承 BaseModel）。"""

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    file_ids: List[str] = Field(..., alias='fileIds')
    to_parent_file_id: str = Field(..., alias='toParentFileId')
    to_user_id: Optional[str] = Field(None, alias='toUserId')
    file_ext_infos: Optional[List[Dict[str, Any]]] = Field(None, alias='fileExtInfos')
    tag_list: Optional[List[Dict[str, Any]]] = Field(None, alias='tagList')

    # 轮询参数，由 _poll 读取，不参与 to_payload 序列化
    poll_interval: float = Field(2.0, exclude=True)
    poll_max_attempts: int = Field(60, exclude=True)

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'fileIds': list(self.file_ids),
            'toParentFileId': self.to_parent_file_id,
        }
        if self.to_user_id:
            payload['toUserId'] = self.to_user_id
        if self.file_ext_infos:
            payload['fileExtInfos'] = list(self.file_ext_infos)
        if self.tag_list:
            payload['tagList'] = list(self.tag_list)
        return payload


class BatchCopyPollResponse(AsyncPollResponse):
    """批量复制任务的轮询结果。

    状态取自 ``data.taskInfo.status``（终态字符串 ``'Succeed'``），扩展字段
    ``batch_file_results`` 对应 ``data.batchFileResults``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    batch_file_results: Optional[List[Dict[str, Any]]] = Field(
        default=None, alias='batchFileResults'
    )

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'BatchCopyPollResponse':
        data = raw.get('data') or {}
        info = data.get('taskInfo') or {}
        status_str = str(info.get('status') or '').strip()
        status_int = 3 if status_str == 'Succeed' else 0
        status_text = '任务成功' if status_int == 3 else (status_str or '未知状态')
        task_id_raw = info.get('taskId')
        if task_id_raw is None:
            task_id_raw = data.get('taskId')

        instance = cls(
            status=status_int,
            status_text=status_text,
            task_id=str(task_id_raw) if task_id_raw is not None else '',
            file_url_list=[],
            file_info_list=[],
            trace_id=trace_id,
            batch_file_results=data.get('batchFileResults'),
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


@personal_saas_api_registry.register('batch_copy')
class BatchCopyApi(BaseAsyncApi):
    """批量复制文件/文件夹的异步 API（轮询 task/get 直到 ``taskInfo.status == 'Succeed'``）。"""

    SUBMIT_PATH = '/richlifeApp/personalSaas/file/batchCopy'
    POLL_PATH = '/richlifeApp/personalSaas/task/get'

    TIMEOUT = ApiTimeoutSettings.FILE_BATCH_COPY_SEC
    POLL_TIMEOUT = ApiTimeoutSettings.TASK_GET_SEC

    api_category = 'personal_saas'
    api_label = '批量复制文件'

    def execute(
        self,
        request: BatchCopyRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Union[BatchCopyPollResponse, AsyncSubmitResponse]:
        """``poll=False``（仅提交）时返回 ``AsyncSubmitResponse``，否则轮询到终态。"""
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _poll(
        self,
        task_id: str,
        request: BatchCopyRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> BatchCopyPollResponse:
        """轮询任务直到 ``taskInfo.status == 'Succeed'``、失败或超时。"""
        poll_url = self._resolve_url(self.POLL_PATH)
        interval = request.poll_interval or self.POLL_INTERVAL
        max_attempts = request.poll_max_attempts or self.POLL_MAX_ATTEMPTS
        payload = {'taskId': task_id}
        first_print = False
        extra_info = info_dict if isinstance(info_dict, dict) else {}

        for attempt in range(1, max_attempts + 1):
            raw, trace_id = post_json_with_retry(
                poll_url,
                payload,
                auth_fn=self._auth,
                timeout=self.POLL_TIMEOUT,
                max_retries=self.MAX_RETRIES,
                retry_delay=self.RETRY_DELAY,
                logger=self.logger,
                log_payload=self._redact_payload(payload),
            )

            if not first_print:
                status_log(
                    msg='poll_start',
                    logger=self.logger,
                    info_dict={
                        'api': type(self).__name__,
                        'taskId': task_id,
                        'trace_id': trace_id,
                        **extra_info,
                    },
                    server_type='ASYNC',
                )
                first_print = True

            data = raw.get('data') or {}
            info = data.get('taskInfo') or {}
            status_value = info.get('status')
            ti_code = info.get('code')

            if ti_code is not None and str(ti_code) not in ('0000', ''):
                rows = [
                    {
                        'errCode': r.get('errCode'),
                        'message': r.get('message'),
                        'fileId': (r.get('srcFile') or {}).get('fileId'),
                    }
                    for r in (data.get('batchFileResults') or [])
                    if isinstance(r, dict)
                ]
                raise RuntimeError(
                    f'taskId={task_id} 异步任务失败: code={ti_code} '
                    f'message={info.get("message")} results={rows}'
                )

            status_log(
                msg='poll_attempt',
                logger=self.logger,
                info_dict={
                    'api': type(self).__name__,
                    'taskId': task_id,
                    'trace_id': trace_id,
                    'attempt': attempt,
                    'status': status_value,
                    **extra_info,
                },
                server_type='ASYNC',
            )

            if status_value == 'Succeed':
                response = BatchCopyPollResponse.from_response(raw, trace_id)
                msg = self._format_result_msg(response, poll_url, 'poll', *args, **kwargs)
                status_log(
                    msg=msg,
                    logger=self.logger,
                    info_dict={
                        'api': type(self).__name__,
                        'taskId': task_id,
                        'trace_id': trace_id,
                        **extra_info,
                    },
                    server_type='ASYNC',
                )
                return self._build_result(
                    response, raw, trace_id, *args, task_id=task_id, **kwargs
                )

            if attempt < max_attempts:
                time.sleep(interval)
                continue

        raise TimeoutError(
            f'taskId={task_id} 轮询超时：{max_attempts} 次后任务仍未完成'
        )

    def _build_result(
        self,
        response: Any,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        task_id: str = '',
        **kwargs: Any,
    ) -> BatchCopyPollResponse:
        data = raw.get('data') or {}
        info = data.get('taskInfo') or {}
        status_str = str(info.get('status') or '').strip()
        status_int = 3 if status_str == 'Succeed' else (response.status or 0)
        status_text = (
            '任务成功' if status_int == 3
            else (status_str or response.status_text or '未知状态')
        )
        task_id = task_id or response.task_id or str(info.get('taskId') or '')

        instance = BatchCopyPollResponse(
            status=status_int,
            status_text=status_text,
            task_id=task_id,
            file_url_list=response.file_url_list,
            file_info_list=response.file_info_list,
            trace_id=trace_id,
            batch_file_results=data.get('batchFileResults'),
        )
        object.__setattr__(instance, 'raw', raw)
        return instance
