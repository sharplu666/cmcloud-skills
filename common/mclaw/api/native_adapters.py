#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用(app)后端的请求/响应适配层。

skills 的 Open API 路径被 ``app_endpoint_map`` 改写成 APK 原生端点；
原生网关与 Open API 的**信封结构一致**（``{success, code, message, data}``），
但个别接口的字段名与语义不同，需要在本层抹平：

  * 原生响应大量使用 ``null``（如 ``file/create`` 的 ``exist``），Open API 侧
    是强类型 bool → 递归剔除 None，让 pydantic 默认值生效。
  * ``file/getPath`` 原生只接受单个 ``fileId``，Open API 是 ``fileIds`` 数组 →
    按文件扇出后重新封装成 ``data.items``。
  * ``file/getDownloadUrl`` 原生同上，逐个查询后封装成 ``data.items``。

本层只做**数据形状**转换，不做鉴权与传输：传输复用 ``_http.post_json_with_retry``，
保证重试 / 日志 / trace_id 行为与其它接口一致。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

__all__ = [
    'native_user_id',
    'adapt_native_request',
    'adapt_native_response',
    'fanout_get_path',
    'fanout_get_download_url',
]


def _map():
    """惰性导入映射模块，避免包路径差异导致 import 失败。"""
    try:
        from mclaw.api import app_endpoint_map as m
    except Exception:  # pragma: no cover
        m = None
    return m


def _strip_none(value: Any) -> Any:
    """递归剔除 dict 中的 None 值（list 元素同样处理）。"""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def adapt_native_request(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Open API 请求体 → 原生请求体（当前两套一致，保留为扩展点）。"""
    if not isinstance(payload, dict):
        return payload
    return payload


def adapt_native_response(path: str, raw: Any) -> Any:
    """原生响应 → Open API 兼容响应（递归剔除 None + 补 success）。"""
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    if 'success' not in out:
        out['success'] = str(out.get('code')) == '0000'
    data = out.get('data')
    if isinstance(data, (dict, list)):
        out['data'] = _strip_none(data)
    return out


def _post(host: str, path: str, payload: Dict[str, Any], auth_fn: Callable[[], Dict[str, str]],
          *, timeout: int, max_retries: int, retry_delay: float, logger=None):
    from mclaw.api.base._http import post_json_with_retry
    from mclaw.api.app_endpoint_map import resolve_endpoint
    r_host, r_path = resolve_endpoint(host, path)
    if r_host == host and r_path == path:
        raise RuntimeError('缺少 %s 的原生端点映射' % path)
    url = r_host.rstrip('/') + '/' + r_path.lstrip('/')
    return post_json_with_retry(
        url, payload, auth_fn=auth_fn, timeout=timeout, max_retries=max_retries,
        retry_delay=retry_delay, logger=logger,
    )


def fanout_get_path(host: str, file_ids: List[str], auth_fn, *,
                    timeout: int = 15, max_retries: int = 1, retry_delay: float = 0.5,
                    logger=None) -> Dict[str, Any]:
    """按 fileId 逐个调用原生 ``file/getPath``，封装成 Open API 的 ``data.items``。"""
    items: List[Dict[str, Any]] = []
    code = '0000'
    message = '请求成功'
    for fid in file_ids:
        try:
            raw, _tid = _post(host, '/richlifeApp/personalSaas/file/batchGetPath',
                              {'fileId': fid}, auth_fn, timeout=timeout,
                              max_retries=max_retries, retry_delay=retry_delay, logger=logger)
        except Exception as exc:  # 单条失败不影响其余
            items.append({'fileId': fid, 'errCode': '9999', 'message': str(exc)[:200]})
            continue
        data = raw.get('data') or {}
        ok = str(raw.get('code')) == '0000' and isinstance(data, dict)
        if not ok:
            code = code if code != '0000' else str(raw.get('code') or '0000')
            message = str(raw.get('message') or message)
        items.append({
            'fileId': fid,
            'namePath': str((data or {}).get('namePath') or ''),
            'idPath': str((data or {}).get('idPath') or ''),
            'type': str((data or {}).get('type') or ''),
            'errCode': '0000' if ok else str(raw.get('code') or ''),
            'message': str(raw.get('message') or ''),
        })
    return {'success': True, 'code': code, 'message': message,
            'data': {'items': [_strip_none(i) for i in items]}}


def fanout_get_download_url(host: str, file_ids: List[str], auth_fn, *,
                            user_id: str = '', expire_sec: int = 3600,
                            timeout: int = 15, max_retries: int = 1,
                            retry_delay: float = 0.5, logger=None) -> Dict[str, Any]:
    """按 fileId 逐个调用原生 ``file/getDownloadUrl``，封装成 Open API 的 ``data.items``。"""
    items: List[Dict[str, Any]] = []
    for fid in file_ids:
        payload: Dict[str, Any] = {'fileId': fid, 'expireSec': int(expire_sec)}
        if user_id:
            payload['userId'] = str(user_id)
        try:
            raw, _tid = _post(host, '/richlifeApp/personalSaas/file/batchGetDownloadUrl',
                              payload, auth_fn, timeout=timeout, max_retries=max_retries,
                              retry_delay=retry_delay, logger=logger)
        except Exception as exc:
            items.append({'fileId': fid, 'errCode': '9999', 'message': str(exc)[:200]})
            continue
        data = raw.get('data') or {}
        item = dict(data) if isinstance(data, dict) else {}
        item.setdefault('fileId', fid)
        # 原生 getDownloadUrl 的 errCode/message 常为 null，按外层信封补齐（"0000" 表示该文件取址成功）
        item['errCode'] = item.get('errCode') or (
            '0000' if str(raw.get('code')) == '0000' else str(raw.get('code') or '')
        )
        item['message'] = item.get('message') or str(raw.get('message') or '')
        items.append(_strip_none(item))
    return {'success': True, 'code': '0000', 'message': '请求成功', 'data': {'items': items}}


def native_user_id() -> str:
    """当前会话的 userDomainId（原生 getDownloadUrl / batchGet 的 userId）。"""
    m = _map()
    if not m:
        return ''
    try:
        return str(m.load_session().get('userDomainId') or '')
    except Exception:
        return ''
