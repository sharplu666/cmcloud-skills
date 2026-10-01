#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量移动文件/文件夹到指定目录（异步接口）。

提交后返回任务 ID，需轮询 ``/richlifeApp/personalSaas/task/get`` 获取结果；
单次最多 1000 个文件。接口文档：dev/docs/api/cm-cloud-manage.md 第 540-610 行。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import AsyncPollResponse, BaseAsyncApi
from mclaw.api.base.base_async_api import AsyncSubmitResponse
from mclaw.api.base._http import post_json_with_retry
from mclaw.api.operation import operation_api_registry
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
    'BatchMoveFilesRequest',
    'BatchMoveFilesPollResponse',
    'BatchMoveFilesApi',
]


class BatchMoveFilesRequest(BaseModel):
    """批量移动接口的提交入参。

    本接口属于 cloudId 体系（参数为 ``fileIds`` / ``toParentFileId``），与媒体
    发送型异步基类 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/...）字段不
    重合，故直接继承 ``BaseModel``，自带轮询控制字段供 ``BaseAsyncApi._poll`` 使用。

    Attributes:
        file_ids: 待移动文件 id 列表，最多 1000 个。
        to_parent_file_id: 目标父目录 id；根目录用 ``'/'``。
        poll_interval: 轮询间隔（秒），不进 payload。
        poll_max_attempts: 最大轮询次数，不进 payload。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    file_ids: List[str] = Field(..., alias='fileIds')
    to_parent_file_id: str = Field(..., alias='toParentFileId')

    # 轮询控制（由 BaseAsyncApi._poll 读取，不进 payload）
    poll_interval: float = Field(2.0, exclude=True)
    poll_max_attempts: int = Field(60, exclude=True)

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的两个驼峰字段。"""
        return {
            'fileIds': list(self.file_ids),
            'toParentFileId': self.to_parent_file_id,
        }


class BatchMoveFilesPollResponse(AsyncPollResponse):
    """批量移动任务的轮询结果。

    扩展字段 ``batch_file_results`` 对应响应中的 ``data.batchFileResults``。

    本接口的状态语义与媒体发送型异步接口不同：
      - 状态位于 ``data.taskInfo.status``（非 ``data.status``）
      - 终态值为字符串 ``'Succeed'``（非整数 3）
      - 失败由 ``taskInfo.code`` 非 ``'0000'`` 判定

    故重写 ``from_response`` 从 ``taskInfo`` 解析，对齐
    ``dev/common/ai_space.py:_poll_task`` 的判定逻辑。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    batch_file_results: Optional[List[Dict[str, Any]]] = Field(
        default=None, alias='batchFileResults'
    )

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> 'BatchMoveFilesPollResponse':
        """从批量移动轮询响应构造（状态取自 ``data.taskInfo.status``）。"""
        data = raw.get('data') or {}
        info = data.get('taskInfo') or {}
        status_str = str(info.get('status') or '').strip()
        # 字符串终态映射到基类整数状态，供 is_success 判定
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


@operation_api_registry.register('batch_move_files')
class BatchMoveFilesApi(BaseAsyncApi):
    """批量移动文件/文件夹到指定目录的异步 API。

    本接口的状态语义与基类 ``_poll`` 默认假设不同（见
    ``BatchMoveFilesPollResponse`` docstring），故重写 ``_poll`` 从
    ``data.taskInfo.status`` 判定终态，对齐 ``dev/common/ai_space.py:_poll_task``。
    """

    SUBMIT_PATH = '/richlifeApp/personalSaas/file/batchMoveAsync'
    # 必须覆盖基类默认值（aiService/api/async/task/result），本接口走 task/get
    POLL_PATH = '/richlifeApp/personalSaas/task/get'
    TIMEOUT = ApiTimeoutSettings.FILE_BATCH_MOVE_ASYNC_SEC
    POLL_TIMEOUT = ApiTimeoutSettings.TASK_GET_SEC

    api_category = 'operation'
    api_label = '批量移动文件'

    def execute(
        self,
        request: BatchMoveFilesRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Union[BatchMoveFilesPollResponse, AsyncSubmitResponse]:
        """类型化入口：入参指向 ``BatchMoveFilesRequest``。

        基类 ``execute`` 签名是 ``AsyncSubmitRequest -> AsyncPollResponse``，本接口
        入参/出参与基类不一致（cloudId 体系 + 自定义响应字段），故必须类型化覆盖，
        避免调用方面对泛化的基类类型。实际流程通过 ``super().execute`` 转发，
        响应类型转换由 ``_build_result`` 钩子完成。``poll=False``（仅提交）时
        返回 ``AsyncSubmitResponse``。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _poll(
        self,
        task_id: str,
        request: BatchMoveFilesRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> BatchMoveFilesPollResponse:
        """轮询批量移动任务直到 ``taskInfo.status == 'Succeed'``、失败或超时。

        与基类 ``_poll`` 的差异：
          - 状态位于 ``data.taskInfo.status``（非 ``data.status``）
          - 终态值为字符串 ``'Succeed'``（非整数 3）
          - 失败由 ``taskInfo.code`` 非 ``'0000'`` 判定

        对齐 ``dev/common/ai_space.py:_poll_task``。
        """
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

            # 失败：taskInfo.code 非 0000（对齐老版本 _poll_task）
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
                response = BatchMoveFilesPollResponse.from_response(raw, trace_id)
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
                return self._build_result(response, raw, trace_id, *args, **kwargs)

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
        **kwargs: Any,
    ) -> BatchMoveFilesPollResponse:
        """重写基类钩子：把 ``AsyncPollResponse`` 转成 ``BatchMoveFilesPollResponse``。

        从 ``raw.data.taskInfo`` 重算 status（不依赖基类对 ``data.status`` 的解析），
        确保 ``is_success`` 判定正确，并填充扩展字段 ``batchFileResults``。
        """
        data = raw.get('data') or {}
        info = data.get('taskInfo') or {}
        status_str = str(info.get('status') or '').strip()
        status_int = 3 if status_str == 'Succeed' else (response.status or 0)
        status_text = (
            '任务成功' if status_int == 3
            else (status_str or response.status_text or '未知状态')
        )
        task_id = response.task_id or str(info.get('taskId') or '')

        instance = BatchMoveFilesPollResponse(
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
