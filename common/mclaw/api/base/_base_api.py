#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BaseSyncApi / BaseAsyncApi 的共享基础设施。

本模块承载同步与异步基类**完全相同**的成员，避免双份拷贝：

  - HTTP 配置类属性：``TIMEOUT`` / ``MAX_RETRIES`` / ``RETRY_DELAY``
  - registry 元信息：``api_category`` / ``api_label``
  - ``__init__``：注入 host / auth_fn / logger / redact_params
  - ``_redact_payload``：payload 脱敏钩子（仅作用于日志）
  - ``_build_result``：execute 返回值构造钩子
  - ``_build_result_dict``：终态日志的"完整原始响应"数据源（返回 ``response.raw``）
  - ``_format_result_msg``：终态日志格式化（url + verb 区分 sync/async）
  - ``_response_success``：兼容 sync(``success``) 与 async(``is_success``) 的成功判定

PATH 校验由各子基类自己做（``BaseSyncApi`` 校验 ``PATH``、``BaseAsyncApi``
校验 ``SUBMIT_PATH``），故 ``_BaseApi.__init__`` 不涉及路径常量。

所有 import 以顶层 ``common/`` 目录为 sys.path 根（详见 README.md）。
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, List, Optional

from mclaw.utils.settings import ApiTimeoutSettings, HttpSettings

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.base')


__all__ = ['_BaseApi']


class _BaseApi(ABC):
    """同步/异步接口基类共享的基础设施。

    子基类（``BaseSyncApi`` / ``BaseAsyncApi``）继承本类后，只需补充各自独有
    的路径常量、``execute`` 主流程与响应解析逻辑；本类提供的成员**无需重写**
    即可直接复用。

    本类不可直接实例化（``ABC``），且不校验任何路径常量——路径校验是子基类
    的职责（``PATH`` vs ``SUBMIT_PATH`` 命名不同，无法在公共层统一）。
    """

    # ──────────────────────────── HTTP 配置（子类可覆盖）───────────────────────────
    TIMEOUT: int = ApiTimeoutSettings.DEFAULT_SEC
    MAX_RETRIES: int = HttpSettings.DEFAULT_MAX_RETRIES
    RETRY_DELAY: float = HttpSettings.DEFAULT_RETRY_DELAY_SEC

    # ──────────────────────────── registry 元信息（可选）───────────────────────────
    api_category: str = 'misc'   # 分类，如 'detect' / 'image' / 'avatar'
    api_label: str = ''          # 中文标签，如 '人脸检测'

    # ──────────────────────────── 构造 ────────────────────────────

    def __init__(
        self,
        host: str,
        auth_fn: Any,
        logger: Any = None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        """注入公共依赖。

        Args:
            host: API 域名（末尾 ``/`` 会被 strip）。
            auth_fn: 返回鉴权 headers dict 的可调用，每次请求前调用。
            logger: 日志记录器；为 None 使用模块默认 logger。
            redact_params: 需在日志中脱敏的 payload key 列表。
        """
        self.host = host.rstrip('/')
        self._auth = auth_fn
        self.logger = logger or _default_logger
        self._redact_params: List[str] = list(redact_params or [])

    # ──────────────────────────── 端点解析（Open API -> APK 原生）────────────────────────────

    def _resolve_url(self, path: str, host: Optional[str] = None) -> str:
        """把接口 PATH 解析成完整 URL。

        经 ``mclaw.api.app_endpoint_map.resolve_endpoint`` 把 (host, path) 改写成 APK 里
        功能等价的原生端点；未命中映射表时原样返回。
        """
        base_host = (host or self.host or '').rstrip('/')
        try:
            from mclaw.api.app_endpoint_map import resolve_endpoint
        except Exception:  # 映射模块缺失时退回旧行为
            return base_host + '/' + path.lstrip('/')
        resolved_host, resolved_path = resolve_endpoint(base_host, path)
        return resolved_host.rstrip('/') + '/' + resolved_path.lstrip('/')

    # ──────────────────────────── 脱敏 ────────────────────────────

    def _redact_payload(
        self,
        payload: Dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """payload 脱敏钩子：返回一份过滤后的 dict 仅供日志输出。

        默认按 key 名精确匹配移除：payload 的 key 在 ``self._redact_params``
        中则从返回值剔除。**只作用于日志展示**，实际请求仍用原 payload。

        子类可重写以实现：
          - 子串匹配（``any(rp in k for rp in self._redact_params)``）
          - 值替换（``{**payload, 'fileUrl': '***'}``）
          - 递归处理嵌套 dict / list
        """
        if not self._redact_params:
            return payload
        return {
            k: v for k, v in payload.items()
            if k not in self._redact_params
        }

    # ──────────────────────────── 结果构造钩子 ────────────────────────────

    def _build_result(
        self,
        response: Any,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """构造 execute / _poll 返回值。默认返回 response。

        子类重写本方法以返回携带额外业务字段的扩展类型，无需重写整个 execute
        也无需新增业务函数。签名包含 raw / trace_id 便于子类构造扩展返回值。

        典型模式：

            class MyResult(SyncResponse):
                extra_field: str = ''

            class MyApi(BaseSyncApi):
                def _build_result(self, response, raw, trace_id, *a, **kw):
                    return MyResult(
                        **response.model_dump(by_alias=True, exclude_none=True),
                        trace_id=trace_id,
                        raw=raw,
                        extra_field=derive_from(raw),
                    )
        """
        return response

    # ──────────────────────────── 终态日志 ────────────────────────────

    def _build_result_dict(
        self,
        response: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """构造终态日志的结果 dict。

        默认返回完整 ``response.raw``（原始响应 JSON），保证 sync/async 都能
        **完整打印**原始响应。子类需要剔除字段、截断 list 或追加摘要时重写本方法。
        """
        return response.raw

    def _format_result_msg(
        self,
        response: Any,
        url: str,
        verb: str,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """构造终态日志的 msg 字段。

        风格对齐 ``_http.post_json_with_retry``：
        ``[{cls}._format_result_msg] {verb} {url} <result>. result={...}.``

        Args:
            response: 终态响应（SyncResponse / AsyncPollResponse 或子类）。
            url: 本次请求的完整 URL（sync=提交接口、async=轮询接口）。
            verb: 动词，``'execute'``（sync）或 ``'poll'``（async），区分两种基类。
        """
        result_dict = self._build_result_dict(response, *args, **kwargs)
        result = 'success' if self._response_success(response) else 'fail'
        prefix = f'[{type(self).__name__}._format_result_msg]'
        return f'{prefix} {verb} {url} {result}. result={result_dict}.'

    @staticmethod
    def _response_success(response: Any) -> bool:
        """兼容 sync(``success``) 与 async(``is_success``) 的成功判定。"""
        if hasattr(response, 'is_success'):
            return bool(response.is_success)
        return bool(getattr(response, 'success', False))
