#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""异步接口基类模版（Pydantic v2）。

适用场景：提交后返回 taskId，需要轮询直到任务终态（如文生图、漫画风、扩图等
绝大部分 AI 图片能力）。

语义对齐 dev/skills/text_to_image/scripts/utils.py:poll_task_result：
  - 终态 status in (3, 4, 5)：直接返回，不再校验 success/code
  - 非终态 (1, 2)：必须 success=True 且 code='0000'，否则抛 RuntimeError
  - 缺 status 字段：按失败抛错

HTTP 配置 / 脱敏 / 终态日志 / 结果构造钩子全部继承自 ``base._base_api._BaseApi``，
本模块只定义异步流程独有的 ``execute`` + ``_poll`` + 轮询控制类属性。

Pydantic 化后字段用 snake_case + alias，构造与序列化见 base_sync_api.py 注释。
"""

from __future__ import annotations

import time
import traceback
import uuid
from abc import ABC
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger, status_log
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.async')

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)

from mclaw.api.base._base_api import _BaseApi
from mclaw.api.base._http import post_json_with_retry
from mclaw.shared.progress import ProgressRecord


__all__ = [
    'AsyncSubmitRequest',
    'AsyncSubmitResponse',
    'AsyncPollResponse',
    'BaseAsyncApi',
]


# ──────────────────────────── 任务状态常量 ────────────────────────────

TASK_STATUS_PENDING = 1
TASK_STATUS_PROCESSING = 2
TASK_STATUS_SUCCESS = 3
TASK_STATUS_FAILED = 4
TASK_STATUS_EXPIRED = 5

TASK_STATUS_TEXT = {
    1: '待处理',
    2: '处理中',
    3: '任务成功',
    4: '任务失败',
    5: '已过期',
}

TERMINAL_STATUSES = (TASK_STATUS_SUCCESS, TASK_STATUS_FAILED, TASK_STATUS_EXPIRED)
SUCCESS_CODE = '0000'


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class AsyncSubmitRequest(BaseModel):
    """异步接口入参基类。

    提交参数 + 轮询控制参数合并在一起。子类扩展业务字段并继承默认 to_payload。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    # 提交参数
    send_type: int = Field(1, alias='sendType')
    file_url: Optional[str] = Field(None, alias='fileUrl')
    file_id: Optional[str] = Field(None, alias='fileId')
    image_ext: Optional[str] = Field(None, alias='imageExt')
    source_task_id: Optional[int] = Field(None, alias='sourceTaskId')

    # 轮询控制（被基类 _poll 使用，不参与 payload）
    poll_interval: float = Field(2.0, exclude=True)
    poll_max_attempts: int = Field(60, exclude=True)

    def to_payload(self) -> Dict[str, Any]:
        """默认序列化提交 payload。子类按需重写。"""
        return self.model_dump(by_alias=True, exclude_none=True)


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class AsyncSubmitResponse(BaseModel):
    """异步提交响应（提交接口返回值）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    success: bool
    # code 兼容 str 与 int：成功多为 '0000'，部分错误响应返回整型错误码
    code: Union[str, int] = ''
    message: str = ''
    task_id: Optional[str] = Field(None, alias='taskId')
    queue_offset: Optional[int] = Field(None, alias='queueOffset')
    trace_id: str = ''
    raw: Dict[str, Any] = Field(default_factory=dict, exclude=True)

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> 'AsyncSubmitResponse':
        # taskId/queueOffset 在 data 嵌套层，需手动展开
        data = raw.get('data') or {}
        merged = {**raw, **data, 'trace_id': trace_id}
        # 兼容错误响应：缺 success 时按 code 推导，避免 model_validate 抛错
        if 'success' not in merged:
            merged['success'] = str(merged.get('code')) == SUCCESS_CODE
        instance = cls.model_validate(merged)
        object.__setattr__(instance, 'raw', raw)
        return instance


class AsyncPollResponse(BaseModel):
    """异步轮询最终结果。

    字段均由 from_response 从原始响应展平计算，不走 alias。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    status: int
    status_text: str = ''
    task_id: str = ''
    file_url_list: List[str] = Field(default_factory=list)
    file_info_list: List[Dict[str, Any]] = Field(default_factory=list)
    trace_id: str = ''
    raw: Dict[str, Any] = Field(default_factory=dict, exclude=True)

    @property
    def is_success(self) -> bool:
        return self.status == TASK_STATUS_SUCCESS

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> 'AsyncPollResponse':
        data = raw.get('data') or {}
        status_value = data.get('status')
        try:
            status_int = int(status_value) if status_value is not None else 0
        except (TypeError, ValueError) as e:
            err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
            status_log(
                msg=f"[AsyncPollResponse.from_response]parse_status_error {err_detail}",
                logger=_default_logger,
                info_dict={'trace_id': trace_id},
                server_type='ASYNC',
            )
            status_int = 0
        status_text = TASK_STATUS_TEXT.get(status_int, '未知状态')

        # 展平 resultList → file_url_list / file_info_list
        file_url_list: List[str] = []
        file_info_list: List[Dict[str, Any]] = []
        for item in data.get('resultList') or []:
            if not isinstance(item, dict):
                continue
            urls = item.get('fileUrlList')
            if isinstance(urls, list):
                file_url_list.extend([u for u in urls if isinstance(u, str)])
            infos = item.get('fileInfoList')
            if isinstance(infos, list):
                file_info_list.extend([i for i in infos if isinstance(i, dict)])

        # 直接构造（避免再次走 model_validate 把展平后的 list 还原回去）
        instance = cls(
            status=status_int,
            status_text=status_text,
            task_id=str(data.get('taskId')) if data.get('taskId') is not None else '',
            file_url_list=file_url_list,
            file_info_list=file_info_list,
            trace_id=trace_id,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


# ──────────────────────────── 基类 ────────────────────────────


class BaseAsyncApi(_BaseApi, ABC):
    """异步接口基类。

    继承 ``_BaseApi`` 获得 HTTP 配置 / 脱敏 / 终态日志 / 结果构造钩子，
    本类只定义异步流程独有的成员。

    子类需要：
      - 必填：SUBMIT_PATH（提交接口路径）
      - 可选：重写 POLL_PATH / TIMEOUT / MAX_RETRIES / RETRY_DELAY（后三者继承自 _BaseApi）
      - 可选：重写 POLL_INTERVAL / POLL_MAX_ATTEMPTS
      - 可选：设置 api_category / api_label，供 registry 元信息使用
    """

    SUBMIT_PATH: str = ''
    POLL_PATH: str = '/richlifeApp/aiService/api/async/task/result'

    POLL_INTERVAL: float = 2.0
    POLL_MAX_ATTEMPTS: int = 60

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        if not self.SUBMIT_PATH:
            raise ValueError(f'{type(self).__name__}.SUBMIT_PATH 未设置')
        super().__init__(host, auth_fn, logger, redact_params)

    def execute(
        self,
        request: AsyncSubmitRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        return_task_id: bool = False,
        poll: bool = True,
        **kwargs: Any,
    ) -> Union[AsyncPollResponse, AsyncSubmitResponse]:
        """提交异步任务并轮询到终态。

        *args / **kwargs 透传给 _poll（用于子类扩展，如自定义轮询节奏）。
        常用 kwargs：timeout / max_retries / retry_delay 覆盖类属性默认。

        info_dict: 额外日志字段；为 dict 时合并到 execute/_poll 所有 status_log 的
            info_dict 中（与 api/taskId/trace_id 一起输出）。透传给 _poll。本方法不会
            原地修改此 dict，会基于它构造新 dict 注入 correlation_id。

        return_task_id: 长时任务兜底开关。默认 False，超时抛 TimeoutError；为 True 时，
            轮询超时不再抛错，而是返回一个 status=处理中、仅 task_id 有效的
            AsyncPollResponse，调用方可后续自行轮询。

        poll: 默认 True（提交后轮询到终态）。False 时仅提交：校验拿到 taskId 后
            返回 ``AsyncSubmitResponse``（含真实 raw / success / code / task_id），
            不进入轮询，由调用方用配套查询接口自行跟进任务（如 personalSaas
            ``task/get``）。是否要求 ``code=='0000'`` 由调用方按自身契约决定。
        """
        # correlation_id 是一次 execute() 调用（提交 + 全部轮询）的唯一标识，
        # 贯穿所有 status_log。每次 HTTP 请求的 trace_id 各不相同，correlation_id
        # 用于跨多次 trace_id 串联同一次完整任务。
        correlation_id = uuid.uuid4().hex
        caller_info = info_dict if isinstance(info_dict, dict) else {}
        extra_info = {**caller_info, 'correlation_id': correlation_id}

        submit_url = self._resolve_url(self.SUBMIT_PATH)
        payload = request.to_payload()
        log_payload = self._redact_payload(payload, *args, **kwargs)
        raw, trace_id = post_json_with_retry(
            submit_url,
            payload,
            auth_fn=self._auth,
            timeout=kwargs.get('timeout', self.TIMEOUT),
            max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
            retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
            logger=self.logger,
            log_payload=log_payload,
        )
        try:
            from mclaw.api.native_adapters import adapt_native_response
            raw = adapt_native_response(self.SUBMIT_PATH, raw)
            submit_resp = AsyncSubmitResponse.from_response(raw, trace_id)
        except Exception:
            # 安全网：提交响应解析异常时，压平 traceback + 原始响应打成单行错误日志，留痕后仍向上抛
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[{type(self).__name__}] submit parse FAILED. raw={raw}. exc={flat_exc}',
                logger=self.logger,
                info_dict={'api': type(self).__name__, 'trace_id': trace_id, **extra_info},
                server_type='ASYNC',
            )
            raise
        # 无论成功/失败，先打印提交响应终态日志（对齐 sync.execute 的行为），
        # 避免失败场景下（如鉴权失败、code 非 0000）看不到完整响应。
        submit_msg = self._format_result_msg(
            submit_resp, submit_url, 'submit', *args, **kwargs
        )
        status_log(
            msg=submit_msg,
            logger=self.logger,
            info_dict={
                'api': type(self).__name__,
                'taskId': submit_resp.task_id,
                'trace_id': trace_id,
                **extra_info,
            },
            server_type='ASYNC',
        )
        if not submit_resp.task_id:
            raise RuntimeError(
                f'提交接口未返回 taskId: {raw}'
            )
        if not poll:
            return submit_resp
        return self._poll(
            submit_resp.task_id,
            request,
            *args,
            info_dict=extra_info,
            return_task_id=return_task_id,
            **kwargs,
        )

    def _poll(
        self,
        task_id: str,
        request: AsyncSubmitRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        return_task_id: bool = False,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """轮询直到终态（3/4/5）或超时。

        return_task_id: 长时任务兜底。默认 False，超时抛 TimeoutError；为 True 时，
            超时返回 status=处理中、仅 task_id 有效的 AsyncPollResponse，调用方可
            后续自行轮询 ``/richlifeApp/aiService/api/async/task/result``。
        """
        poll_url = self._resolve_url(self.POLL_PATH)
        interval = request.poll_interval or self.POLL_INTERVAL
        max_attempts = request.poll_max_attempts or self.POLL_MAX_ATTEMPTS
        payload = {'taskId': task_id}
        first_print = False
        extra_info = info_dict if isinstance(info_dict, dict) else {}

        # 进度提示：让大模型/用户在上下文中感知到当前轮询进度（status_log 仅写文件）。
        print(
            ProgressRecord(
                status='running',
                stage='taskPolling',
                say_to_user=f'开始轮询，最大轮询次数 {max_attempts}',
            ).to_json_line(),
            flush=True,
        )

        for attempt in range(1, max_attempts + 1):
            raw, trace_id = post_json_with_retry(
                poll_url,
                payload,
                auth_fn=self._auth,
                timeout=self.TIMEOUT,
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
            status_value = data.get('status')

            if status_value is None:
                if raw.get('success') is not True or str(raw.get('code')) != SUCCESS_CODE:
                    raise RuntimeError(
                        f'taskId={task_id} 轮询失败 (缺 status 且业务失败): {raw}'
                    )
                raise RuntimeError(
                    f'taskId={task_id} 轮询结果缺 status 字段: {raw}'
                )

            try:
                status_int = int(status_value)
            except (TypeError, ValueError) as e:
                err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
                status_log(
                    msg=f"[{type(self).__name__}._poll]status_error {err_detail}",
                    logger=self.logger,
                    info_dict={
                        'api': type(self).__name__,
                        'taskId': task_id,
                        'trace_id': trace_id,
                        **extra_info,
                    },
                    server_type='ASYNC',
                )
                raise RuntimeError(
                    f'taskId={task_id} status 非整数: {status_value}'
                ) from e

            status_text = TASK_STATUS_TEXT.get(status_int, '未知状态')

            # 进度条：每次轮询打印 已轮询/最大轮询次数，统一走 ProgressRecord 回执格式。
            # 成功终态不说「任务成功」（会被 agent 误读为进程已结束、停止消费后续输出，
            # 卡片等回执要等进程收尾 flush 才出现），改说「正在取回并归档结果…」。
            print(
                ProgressRecord(
                    status='running',
                    stage='taskPolling',
                    say_to_user=(
                        '正在取回并归档结果…'
                        if status_int == TASK_STATUS_SUCCESS
                        else f'轮询中 {attempt}/{max_attempts}，当前状态：{status_text}'
                    ),
                ).to_json_line(),
                flush=True,
            )

            # 每次轮询请求都记录其独有的 trace_id（每次 HTTP 请求不同）+ 当次结果，
            # 这样任意一次轮询都能在服务端日志中独立定位。
            status_log(
                msg='poll_attempt',
                logger=self.logger,
                info_dict={
                    'api': type(self).__name__,
                    'taskId': task_id,
                    'trace_id': trace_id,
                    'attempt': attempt,
                    'status': status_int,
                    'status_text': status_text,
                    **extra_info,
                },
                server_type='ASYNC',
            )

            if status_int in TERMINAL_STATUSES:
                response = AsyncPollResponse.from_response(raw, trace_id)
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

            if raw.get('success') is not True or str(raw.get('code')) != SUCCESS_CODE:
                raise RuntimeError(
                    f'taskId={task_id} 非终态但业务失败: {raw}'
                )

            if status_int in (TASK_STATUS_PENDING, TASK_STATUS_PROCESSING):
                if attempt < max_attempts:
                    time.sleep(interval)
                continue

            raise RuntimeError(
                f'taskId={task_id} status 不在预期范围内: {status_int}'
            )

        # 超时兜底：return_task_id=True 时不抛错，返回 status=处理中、仅 task_id 有效的
        # AsyncPollResponse，调用方可后续自行轮询 /richlifeApp/aiService/api/async/task/result
        if return_task_id:
            print(
                ProgressRecord(
                    status='running',
                    stage='taskPolling',
                    say_to_user=(
                        f'已达最大轮询次数 {max_attempts}，任务仍未完成，'
                        f'返回 taskId={task_id} 供后续查询'
                    ),
                ).to_json_line(),
                flush=True,
            )
            fallback = AsyncPollResponse(
                status=TASK_STATUS_PROCESSING,
                status_text=TASK_STATUS_TEXT[TASK_STATUS_PROCESSING],
                task_id=task_id,
                trace_id='',
            )
            object.__setattr__(fallback, 'raw', {})
            return fallback

        raise TimeoutError(
            f'taskId={task_id} 轮询超时：{max_attempts} 次后任务仍未完成'
        )
