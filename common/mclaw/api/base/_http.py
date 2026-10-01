#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.api 内部共享 HTTP 工具。

提供：
  - extract_trace_id: 从 requests.Response 提取 trace_id
  - post_json_with_retry: 统一 POST JSON + 重试 + CLI timing/failapi
  - post_xml_with_retry: 统一 POST XML + 重试 + CLI timing/failapi
  - post_multipart_with_retry: 统一 POST multipart/form-data + 重试 + CLI timing/failapi

日志：每次请求（成功/失败）记录 url + payload；成功为 INFO（含 trace_id、
elapsed_ms），失败为 WARNING。仅写日志文件，不进 stdout/CLI 输出。
"""

from __future__ import annotations

import json
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

from mclaw.utils.settings import ApiTimeoutSettings, HttpSettings

try:
    from mclaw.utils.logger import setup_logger, status_log
    _default_logger = setup_logger(
        name='mclaw.api.http',
        stdout=False,
        stderr=True,
        level='warning',
    )
except Exception:  # pragma: no cover - logger 不可用时降级到 logging
    import logging
    import sys

    _default_logger = logging.getLogger('mclaw.api.http')
    _default_logger.setLevel(logging.INFO)
    _default_logger.propagate = False
    if not _default_logger.handlers:
        _fallback = logging.StreamHandler(stream=sys.stderr)
        _fallback.setFormatter(logging.Formatter('%(levelname)s|%(message)s'))
        _default_logger.addHandler(_fallback)

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)


__all__ = [
    'extract_trace_id',
    'extract_http_error_msg',
    'post_json_with_retry',
    'post_xml_with_retry',
    'post_multipart_with_retry',
    'record_cli_business_fail',
]

_T = TypeVar('_T')


def extract_http_error_msg(response: Optional[requests.Response]) -> str:
    """从 HTTP 响应 body 提取可读错误信息（供 JSON POST 与直传上传复用）。"""
    return _extract_http_error_msg(response)


def _extract_http_error_msg(response: Optional[requests.Response]) -> str:
    if response is None:
        return ''
    body = (response.text or '').strip()
    if not body:
        return ''
    try:
        data = response.json()
        if isinstance(data, dict):
            msg = data.get('message')
            if msg is not None and str(msg).strip():
                return str(msg)
    except ValueError:
        pass
    return body


def _is_non_retryable_auth_error(exc: Exception) -> bool:
    """鉴权/配置类错误不应重试。"""
    return type(exc).__name__ in ('AuthConfigError', 'AuthDecryptError')


def _cli_api_path(url: str) -> str:
    path = (urlparse(url).path or url or '').strip()
    if path and not path.startswith('/'):
        path = '/' + path
    return path


def _trace_id_token(trace: str) -> str:
    text = str(trace or '').strip()
    if text.startswith('trace_id='):
        return text[len('trace_id='):].strip()
    if text.startswith('x-yun-tid='):
        return text[len('x-yun-tid='):].strip()
    return text


def _fail_response_payload(resp: Optional[requests.Response]) -> Any:
    if resp is None:
        return {}
    json_fn = getattr(resp, 'json', None)
    if callable(json_fn):
        try:
            return json_fn()
        except (ValueError, TypeError, AttributeError):
            pass
    return (getattr(resp, 'text', None) or '').strip() or {}


def record_cli_business_fail(
    path: str,
    error: str,
    request: Any = None,
    response: Any = None,
) -> None:
    """业务失败时写 failapi。无 cli_timing 时静默跳过。"""
    api_path = path if str(path).startswith('/') else '/' + str(path).lstrip('/')
    try:
        from cli_timing import record_fail_api
    except ImportError:
        return
    record_fail_api(
        api_path,
        error,
        request={} if request is None else request,
        response={} if response is None else response,
    )


def _observe_cli_http(
    url: str,
    elapsed_ms: float,
    *,
    trace: str = '',
    error: Optional[str] = None,
    request: Any = None,
    response: Any = None,
) -> None:
    """登记 CLI timing；失败时写入 failapi（请求体/返回体）。无 cli_timing 时静默跳过。"""
    path = _cli_api_path(url)
    try:
        from cli_trace import capture_trace_string, set_last_api_path
    except ImportError:
        capture_trace_string = None  # type: ignore[assignment]
        set_last_api_path = None  # type: ignore[assignment]
    if set_last_api_path:
        set_last_api_path(path)
    if trace and capture_trace_string:
        capture_trace_string(
            trace if ('=' in str(trace)) else f'trace_id={trace}'
        )
    try:
        from cli_timing import record_api_timing
    except ImportError:
        return
    record_api_timing(path, elapsed_ms, trace_id=_trace_id_token(trace))
    if error:
        record_cli_business_fail(path, error, request=request, response=response)


def extract_trace_id(response: Optional[requests.Response]) -> str:
    """从响应 headers 提取 trace_id。

    Args:
        response: requests.Response 对象，允许 None

    Returns:
        trace_id 原始值；无则空串
    """
    if response is None:
        return ''
    return (response.headers or {}).get('trace_id', '').strip()


def _decode_json_body(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except ValueError as json_exc:
        raise ValueError(_extract_http_error_msg(resp) or str(json_exc)) from json_exc


def _decode_xml_text(resp: requests.Response) -> str:
    text = resp.text or ''
    try:
        ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError((text or '').strip() or '响应非 XML') from exc
    return text


def _post_with_retry(
    url: str,
    *,
    auth_fn: Callable[[], Dict[str, str]],
    timeout: int,
    max_retries: int,
    retry_delay: float,
    retry_on: Optional[Tuple[type, ...]],
    logger,
    log_name: str,
    request_obs: Any,
    log_display: Any,
    send: Callable[[Dict[str, str]], requests.Response],
    decode: Callable[[requests.Response], _T],
    http_error_msg: Callable[[Optional[requests.Response]], str],
) -> Tuple[_T, str]:
    log = logger or _default_logger
    catch = retry_on if retry_on is not None else (Exception,)
    max_attempts = max_retries + 1
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            headers = auth_fn() if auth_fn else {}
        except Exception as e:
            err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
            status_log(
                msg=f"[_http.{log_name}]auth_error {err_detail}",
                logger=log,
                info_dict={},
                server_type='HTTP',
            )
            if _is_non_retryable_auth_error(e):
                raise
            last_exc = e
            if attempt <= max_retries:
                time.sleep(retry_delay)
                continue
            break

        try:
            t0 = time.time()
            resp = send(headers)
            resp.raise_for_status()
            elapsed_ms = int((time.time() - t0) * 1000)
            trace_id = extract_trace_id(resp)
            try:
                decoded = decode(resp)
            except ValueError as decode_exc:
                detail = str(decode_exc).strip() or '响应解析失败'
                _observe_cli_http(
                    url,
                    elapsed_ms,
                    trace=trace_id,
                    error=detail,
                    request=request_obs,
                    response=_fail_response_payload(resp),
                )
                last_exc = ValueError(detail)
                status_log(
                    msg=f"[_http.{log_name}]request url error: {detail}. payload: {log_display}.",
                    logger=log,
                    info_dict={"trace_id": trace_id, "elapsed_ms": elapsed_ms},
                    server_type='HTTP',
                )
                break
            status_log(
                msg=f"[_http.{log_name}]request url: {url}. payload: {log_display}.",
                logger=log,
                info_dict={"trace_id": trace_id, "elapsed_ms": elapsed_ms},
                server_type='HTTP',
            )
            _observe_cli_http(url, elapsed_ms, trace=trace_id, request=request_obs)
            return decoded, trace_id
        except catch as e:
            elapsed_ms = int((time.time() - t0) * 1000) if 't0' in locals() else 0
            err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
            status_log(
                msg=f"[_http.{log_name}]request url error: {err_detail}. payload: {log_display}.",
                logger=log,
                info_dict={"elapsed_ms": elapsed_ms},
                server_type='HTTP',
            )
            response = getattr(e, 'response', None)
            fail_body = _fail_response_payload(response)
            if response is not None:
                body_msg = http_error_msg(response)
                last_exc = RuntimeError(body_msg) if body_msg else e
            else:
                last_exc = e
            is_last = attempt > max_retries
            _observe_cli_http(
                url,
                elapsed_ms,
                trace=extract_trace_id(response) if response is not None else '',
                error=(str(last_exc) or '请求失败') if is_last else None,
                request=request_obs,
                response=fail_body if is_last else None,
            )
            if attempt <= max_retries:
                time.sleep(retry_delay)
                continue
            break

    api_path = urlparse(url).path or url
    if isinstance(last_exc, requests.exceptions.Timeout):
        raise RuntimeError(f'请求超时: {api_path}') from last_exc
    if isinstance(last_exc, (json.JSONDecodeError, ValueError)):
        detail = str(last_exc).strip()
        suffix = f': {detail}' if detail else '。'
        raise RuntimeError(f'响应解析失败{suffix}') from last_exc
    raise RuntimeError(
        f'请求失败: {url} 重试 {max_retries} 次后仍失败: {last_exc}'
    ) from last_exc


def post_json_with_retry(
    url: str,
    payload: Dict[str, Any],
    *,
    auth_fn: Callable[[], Dict[str, str]],
    timeout: int = ApiTimeoutSettings.DEFAULT_SEC,
    max_retries: int = HttpSettings.DEFAULT_MAX_RETRIES,
    retry_delay: float = HttpSettings.DEFAULT_RETRY_DELAY_SEC,
    retry_on: Optional[Tuple[type, ...]] = None,
    logger=None,
    log_payload: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """统一 POST JSON：重试、timing / failapi。成功日志由 BaseSyncApi 终态打。"""
    display = log_payload if log_payload is not None else payload
    return _post_with_retry(
        url,
        auth_fn=auth_fn,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        retry_on=retry_on,
        logger=logger,
        log_name='post_json_with_retry',
        request_obs=payload,
        log_display=display,
        send=lambda headers: requests.post(
            url, json=payload, headers=headers, timeout=timeout,
        ),
        decode=_decode_json_body,
        http_error_msg=_extract_http_error_msg,
    )


def post_xml_with_retry(
    url: str,
    xml_body: str,
    *,
    auth_fn: Callable[[], Dict[str, str]],
    timeout: int = ApiTimeoutSettings.DEFAULT_SEC,
    max_retries: int = HttpSettings.DEFAULT_MAX_RETRIES,
    retry_delay: float = HttpSettings.DEFAULT_RETRY_DELAY_SEC,
    retry_on: Optional[Tuple[type, ...]] = None,
    logger=None,
) -> Tuple[str, str]:
    """统一 POST XML：重试、timing / failapi。HTTP 200 但非 XML 记为解析失败。"""
    return _post_with_retry(
        url,
        auth_fn=auth_fn,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        retry_on=retry_on,
        logger=logger,
        log_name='post_xml_with_retry',
        request_obs=xml_body,
        log_display=xml_body,
        send=lambda headers: requests.post(
            url, data=xml_body, headers=headers, timeout=timeout,
        ),
        decode=_decode_xml_text,
        http_error_msg=lambda resp: (resp.text or '').strip() if resp is not None else '',
    )


def post_multipart_with_retry(
    url: str,
    data: Dict[str, Any],
    files: List[Tuple[str, Tuple[str, Any, str]]],
    *,
    auth_fn: Callable[[], Dict[str, str]],
    timeout: int = ApiTimeoutSettings.DEFAULT_SEC,
    max_retries: int = HttpSettings.DEFAULT_MAX_RETRIES,
    retry_delay: float = HttpSettings.DEFAULT_RETRY_DELAY_SEC,
    retry_on: Optional[Tuple[type, ...]] = None,
    logger=None,
    log_payload: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """统一 POST multipart/form-data：重试、timing / failapi。成功日志由 BaseSyncApi 终态打。

    ``files`` 为 requests 形式 ``[(field, (filename, content, content_type))]``；
    ``Content-Type``（含 boundary）由 requests 自动生成，鉴权头中**不要**预设它。
    文件正文不进 ``request_obs`` / 日志，替换为 ``{field, name, size, type}`` 摘要。
    """
    display = log_payload if log_payload is not None else data
    file_summary = [
        {'field': field, 'name': name, 'size': len(content), 'type': ctype}
        for field, (name, content, ctype) in files
    ]
    return _post_with_retry(
        url,
        auth_fn=auth_fn,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        retry_on=retry_on,
        logger=logger,
        log_name='post_multipart_with_retry',
        request_obs={'data': data, 'files': file_summary},
        log_display=display,
        send=lambda headers: requests.post(
            url, data=data, files=files, headers=headers, timeout=timeout,
        ),
        decode=_decode_json_body,
        http_error_msg=_extract_http_error_msg,
    )