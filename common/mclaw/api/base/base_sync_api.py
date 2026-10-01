#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步接口基类模版（Pydantic v2）。

适用场景：请求即返回最终结果（如 ai_portrait_face_detect 同步写真人脸检测）。
异步能力（提交→轮询）请使用 base_async_api.BaseAsyncApi。

Pydantic 化后：
  - 字段用 snake_case + `Field(alias='camelCase')`，调用方既能 `send_type=1` 也能 `sendType=1` 构造
  - `to_payload()` 默认走 `model_dump(by_alias=True, exclude_none=True)`，无需手写
  - `from_response()` 默认**展平 data 嵌套层**（与 AsyncSubmitResponse 一致），
    走 `model_validate`，自动类型校验 + 嵌套解析
  - 未知字段在 Request 端禁止（extra='forbid'），在 Response 端忽略（extra='ignore'）

HTTP 配置 / 脱敏 / 终态日志 / 结果构造钩子全部继承自 ``base._base_api._BaseApi``，
本模块只定义同步流程独有的 ``execute`` + ``_parse_response``。

使用方式（详见 README.md / how_to_add_api.md）：

    from typing import Any, Dict
    from pydantic import BaseModel, Field
    from mclaw.api.base.base_sync_api import BaseSyncApi, SyncRequest, SyncResponse

    class FaceDetectRequest(SyncRequest):
        detect_mode: int = Field(0, alias='detectMode')
        # to_payload 自动序列化（含 sendType/imageExt/detectMode + 条件字段）

    class FaceDetectResponse(SyncResponse):
        exist_face: bool = Field(False, alias='existFace')
        face_count: int = Field(0, alias='faceCount')
        # from_response 自动展平 data，子类一般无需重写

    class FaceDetectApi(BaseSyncApi):
        PATH = '/richlifeApp/aiService/api/image/detect/face'

    api = FaceDetectApi(host='https://...', auth_fn=get_auth_header)
    resp = api.execute(FaceDetectRequest(send_type=1, file_url='https://...'))
"""

from __future__ import annotations

from abc import ABC
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from mclaw.utils.settings import HttpSettings

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger, status_log
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.sync')

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)

from mclaw.api.base._base_api import _BaseApi
from mclaw.api.base._http import post_json_with_retry, record_cli_business_fail


__all__ = ['SyncRequest', 'SyncResponse', 'BaseSyncApi']


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class SyncRequest(BaseModel):
    """同步接口入参基类。

    通用字段（按接口文档原样 camelCase alias）：
      - sendType (1=url / 3=fileId)
      - fileUrl / fileId / imageExt / sourceTaskId

    子类扩展字段时配 `Field(alias='业务驼峰名')`。
    to_payload() 默认输出 camelCase + 过滤 None，子类一般无需重写。
    """

    model_config = ConfigDict(
        populate_by_name=True,   # 同时支持 Python 名与 alias 构造
        extra='forbid',          # 拒绝未知字段（防拼写错）
    )

    send_type: int = Field(1, alias='sendType')
    file_url: Optional[str] = Field(None, alias='fileUrl')
    file_id: Optional[str] = Field(None, alias='fileId')
    image_ext: Optional[str] = Field(None, alias='imageExt')
    source_task_id: Optional[int] = Field(None, alias='sourceTaskId')

    def to_payload(self) -> Dict[str, Any]:
        """默认序列化：camelCase alias + 过滤 None 字段。

        若业务需要条件字段（如 send_type=1 时输出 fileUrl，否则 fileId），
        exclude_none 已自动处理（None 字段不出现在 payload）。
        子类可重写以定制 wrapper 结构（如 {'searchParam': {...}}）。
        """
        return self.model_dump(by_alias=True, exclude_none=True)


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class SyncResponse(BaseModel):
    """同步接口出参基类。

    默认**展平 data 嵌套层**（与 AsyncSubmitResponse 行为一致）：
    `{success, code, message, data: {业务字段}}` 会把 `data` 内字段提升到顶层，
    子类的业务字段（带 alias）即可被自动填充，**无需重写 from_response**。

    `extra='ignore'` 容忍服务端新增字段；`raw` 保留原始响应供排查与日志。
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra='ignore',          # 容忍服务端新增字段
    )

    success: bool
    # code 兼容 str 与 int：成功多为 '0000'，部分错误响应返回整型错误码（如 11000）
    code: Union[str, int] = ''
    message: str = ''
    trace_id: str = ''
    # 原始响应 dict，调试用；不参与序列化
    raw: Dict[str, Any] = Field(default_factory=dict, exclude=True)

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'SyncResponse':
        """从原始响应构造，默认展平 data 嵌套层。

        服务端响应 `{success, code, data: {bizField}}` 时，data 内字段会被
        提升到顶层与外层字段合并后再 model_validate。子类若需特殊解析可重写，
        但绝大多数场景直接继承即可（参考 MergeFileSearchResponse）。

        兼容错误响应：后端错误响应可能省略 ``success`` 字段、``code`` 为整型，
        此处缺 ``success`` 时按 ``code`` 推导（``'0000'`` 视为成功），避免
        ``model_validate`` 直接抛 ValidationError。
        """
        data = raw.get('data') or {}
        merged = {**raw, **data, 'trace_id': trace_id}
        if 'success' not in merged:
            merged['success'] = str(merged.get('code')) == '0000'
        instance = cls.model_validate(merged)
        object.__setattr__(instance, 'raw', raw)
        return instance


# ──────────────────────────── 基类 ────────────────────────────


class BaseSyncApi(_BaseApi, ABC):
    """同步接口基类。

    继承 ``_BaseApi`` 获得 HTTP 配置 / 脱敏 / 终态日志 / 结果构造钩子，
    本类只定义同步流程独有的成员。

    子类需要：
      - 必填：PATH（接口路径，如 '/richlifeApp/aiService/api/image/detect/face'）
      - 可选：重写 TIMEOUT / MAX_RETRIES / RETRY_DELAY（继承自 _BaseApi）
      - 可选：重写 _parse_response 定制响应解析
      - 可选：设置 api_category / api_label，供 registry 元信息使用
    """

    PATH: str = ''

    # 业务码兜底重试（opt-in）：默认关闭。错误码集按 API 类各自配置
    # （RETRY_ERROR_CODE_LIST，每个接口的错误码不同；默认空集=休眠），也可经
    # kwargs['retry_error_code_list'] 按调用覆盖。命中时同参重发 2 次（固定，
    # 不进 settings）；触发口径：str(code) != '0000' 且 str(code) ∈ 清单。
    BUSINESS_CODE_RETRY_ENABLED: bool = False
    RETRY_ERROR_CODE_LIST: frozenset = frozenset()
    BUSINESS_RETRY_MAX_RETRIES: int = 2

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        if not self.PATH:
            raise ValueError(f'{type(self).__name__}.PATH 未设置')
        super().__init__(host, auth_fn, logger, redact_params)

    def execute(
        self,
        request: SyncRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SyncResponse:
        """发起一次同步请求，返回 SyncResponse（或子类）。

        *args / **kwargs 用于子类扩展与按调用覆盖：
          - timeout / max_retries / retry_delay：覆盖类属性默认值
          - 其它 kwargs 透传给 _parse_response / _format_result_msg

        info_dict: 额外日志字段；为 dict 时合并到 status_log 的 info_dict 中，
            与默认的 api/trace_id 一起输出，便于按 requestId/userId 等追踪。
        """
        url = self._resolve_url(self.PATH)
        payload = request.to_payload()
        extra_info = info_dict if isinstance(info_dict, dict) else {}
        log_payload = self._redact_payload(payload, *args, **kwargs)
        raw, trace_id = None, ''
        error_code_list = frozenset(
            kwargs.get('retry_error_code_list') or self.RETRY_ERROR_CODE_LIST
        )
        max_business_retries = (
            self.BUSINESS_RETRY_MAX_RETRIES if self.BUSINESS_CODE_RETRY_ENABLED else 0
        )
        for attempt in range(1, max_business_retries + 2):
            raw, trace_id = post_json_with_retry(
                url,
                payload,
                auth_fn=self._auth,
                timeout=kwargs.get('timeout', self.TIMEOUT),
                max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
                retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
                logger=self.logger,
                log_payload=log_payload,
            )
            if (
                attempt <= max_business_retries
                and isinstance(raw, dict)
                and str(raw.get('code')) != '0000'
                and str(raw.get('code')) in error_code_list
            ):
                status_log(
                    msg=f'[{type(self).__name__}] business-code retryable, code='
                    f"{raw.get('code')}, retry {attempt}/{max_business_retries}",
                    logger=self.logger,
                    info_dict={'api': type(self).__name__, **extra_info},
                    server_type='SYNC',
                )
                time.sleep(kwargs.get('retry_delay', self.RETRY_DELAY))
                continue
            break
        try:
            from mclaw.api.native_adapters import adapt_native_response
            raw = adapt_native_response(self.PATH, raw)
            response = self._parse_response(raw, trace_id, *args, **kwargs)
            msg = self._format_result_msg(response, url, 'execute', *args, **kwargs)
            if not self._response_success(response):
                err = str(getattr(response, 'message', '') or '').strip() or '业务失败'
                record_cli_business_fail(
                    '/' + self.PATH.lstrip('/'),
                    err,
                    request=payload,
                    response=raw,
                )
        except Exception:
            # 压平 traceback，避免多行破坏 | 分隔日志。
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[{type(self).__name__}] parse/format FAILED. payload={payload}. exc={flat_exc}',
                logger=self.logger,
                info_dict={'api': type(self).__name__, **extra_info},
                server_type='SYNC',
                stdout=True
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
    ) -> SyncResponse:
        """默认调用 SyncResponse.from_response；子类可重写。"""
        return SyncResponse.from_response(raw, trace_id)
