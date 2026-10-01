#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云文件 Service —— 详情、路径、存在性、下载、播放进度、批量改名。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas._models import SubRequest, SubRequestEnvelope
from mclaw.api.personal_saas.batch_get_api import BatchGetRequest
from mclaw.api.personal_saas.batch_get_download_url_api import BatchGetDownloadUrlRequest
from mclaw.api.personal_saas.get_path_api import GetPathRequest

from utils.config import BATCH_SUBREQUEST_MAX
from mclaw.shared.postprocess.merge_normalize import normalize_check_exists_data
from mclaw.shared.postprocess.api_obs import data_dict, err_message, finish

__all__ = [
    'batch_get',
    'batch_get_all',
    'batch_get_path',
    'batch_check_exists',
    'check_exists',
    'batch_download_url',
    'batch_file_update',
]


def batch_get(
    dispatcher: ApiDispatcher,
    file_ids: List[str],
    thumbnail_styles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """批量获取文件详情。返回 batchFileResults list；失败抛 RuntimeError。"""
    request = BatchGetRequest(file_ids=list(file_ids), thumbnail_style_list=thumbnail_styles)
    started = time.perf_counter()
    response = dispatcher.personal_saas.batch_get(request)
    finish('richlifeApp/personalSaas/file/batchGet', started, response)
    if str(response.code or '') != '0000':
        raise RuntimeError(f'batchGet 失败: {err_message(response, "业务失败")}')
    return data_dict(response).get('batchFileResults') or []


def batch_get_all(
    dispatcher: ApiDispatcher,
    file_ids: List[str],
    thumbnail_styles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """分片调用 batchGet（每批最多 BATCH_SUBREQUEST_MAX），合并 batchFileResults。"""
    normalized = list(dict.fromkeys(str(fid or '').strip() for fid in file_ids if str(fid or '').strip()))
    results: List[Dict[str, Any]] = []
    for offset in range(0, len(normalized), BATCH_SUBREQUEST_MAX):
        chunk = normalized[offset: offset + BATCH_SUBREQUEST_MAX]
        results.extend(batch_get(dispatcher, chunk, thumbnail_styles=thumbnail_styles))
    return results


def batch_get_path(dispatcher: ApiDispatcher, file_ids: List[str]) -> List[Dict[str, Any]]:
    """批量获取文件全路径信息。返回原始 items；失败抛 RuntimeError。"""
    if not file_ids:
        return []
    request = GetPathRequest(file_ids=list(file_ids))
    started = time.perf_counter()
    response = dispatcher.personal_saas.get_path(request)
    finish('richlifeApp/personalSaas/file/batchGetPath', started, response)
    if str(response.code or '') != '0000':
        raise RuntimeError(f'batchGetPath 失败: {err_message(response, "业务失败")}')
    return data_dict(response).get('items') or []


def batch_check_exists(
    dispatcher: ApiDispatcher,
    sub_requests: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """批量检查父目录直接子级是否同名（不递归）。单批超 100 自动分片。"""
    if not sub_requests:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for off in range(0, len(sub_requests), BATCH_SUBREQUEST_MAX):
        chunk = sub_requests[off: off + BATCH_SUBREQUEST_MAX]
        seen_ids: set[str] = set()
        items: List[SubRequest] = []
        for req in chunk:
            rid = str(req.get('id') or '').strip()
            parent = str(req.get('parentFileId') or '').strip()
            name = str(req.get('fileName') or '').strip()
            if not rid:
                raise RuntimeError('batchCheckExists 失败：子请求 id 不能为空')
            if rid in seen_ids:
                raise RuntimeError(f'batchCheckExists 失败：子请求 id 重复：{rid!r}')
            seen_ids.add(rid)
            if not parent:
                raise RuntimeError(f'batchCheckExists 失败：子请求 {rid!r} 缺少 parentFileId')
            if not name:
                raise RuntimeError(f'batchCheckExists 失败：子请求 {rid!r} 缺少 fileName')
            body: Dict[str, Any] = {'parentFileId': parent, 'fileName': name}
            op = req.get('operatorId')
            if op is not None:
                body['operatorId'] = int(op)
            items.append(SubRequest(id=rid, body=body))

        started = time.perf_counter()
        response = dispatcher.personal_saas.batch_check_exists(SubRequestEnvelope(sub_request_list=items))
        finish('richlifeApp/personalSaas/file/batchCheckExists', started, response)
        if not response.success:
            raise RuntimeError(f'batchCheckExists 失败: {err_message(response, "业务失败")}')

        rows = response.sub_response_list
        if len(rows) != len(items):
            raise RuntimeError('batchCheckExists 失败：subResponseList 条数与请求不一致')

        chunk_out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            rid = str(row.id or '').strip()
            if not rid:
                raise RuntimeError('batchCheckExists 失败：子响应缺少 id')
            code = str(row.code or '').strip()
            norm = normalize_check_exists_data(row.data if code == '0000' else {})
            chunk_out[rid] = {'code': code, 'message': str(row.message or '').strip(), 'data': norm}

        if set(chunk_out) != {item.id for item in items}:
            raise RuntimeError('batchCheckExists 失败：子响应 id 与请求不一致')
        out.update(chunk_out)

    return out


def check_exists(dispatcher: ApiDispatcher, parent_file_id: str, file_name: str) -> Dict[str, Any]:
    """检查指定父目录下是否存在同名项。返回标准化 data dict。"""
    rows = batch_check_exists(
        dispatcher, [{'id': '0', 'parentFileId': parent_file_id, 'fileName': file_name}]
    )
    row = rows.get('0')
    if not row:
        raise RuntimeError('checkExists 失败：未返回子响应')
    if str(row.get('code') or '').strip() != '0000':
        raise RuntimeError(
            f'checkExists 失败: {row.get("message") or row.get("code") or "未知错误"}, '
            f'parent_file_id={parent_file_id!r}'
        )
    data = row.get('data') or {}
    return data if isinstance(data, dict) else {}


def batch_download_url(dispatcher: ApiDispatcher, file_ids: List[str]) -> Dict[str, str]:
    """批量获取下载地址。返回 {fileId: downloadUrl}；任一文件失败抛 RuntimeError。"""
    request = BatchGetDownloadUrlRequest(file_ids=list(file_ids))
    started = time.perf_counter()
    response = dispatcher.personal_saas.batch_get_download_url(request)
    finish('richlifeApp/personalSaas/file/batchGetDownloadUrl', started, response)
    if str(response.code or '') != '0000':
        raise RuntimeError(f'获取下载URL失败: {err_message(response, "业务失败")}')

    urls: Dict[str, str] = {}
    for item in response.items:
        if item.err_code == '0000':
            urls[item.file_id] = item.url
        else:
            raise RuntimeError(f'文件 {item.file_id} 下载URL获取失败: {item.message}')
    return urls


def batch_file_update(
    dispatcher: ApiDispatcher,
    sub_requests: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """批量更新文件名称等。返回 {子请求 id: {'code','message','data'}}；单批超 100 自动分片。"""
    if not sub_requests:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for off in range(0, len(sub_requests), BATCH_SUBREQUEST_MAX):
        chunk = sub_requests[off: off + BATCH_SUBREQUEST_MAX]
        seen_ids: set[str] = set()
        items: List[SubRequest] = []
        for req in chunk:
            rid = str(req.get('id') or '').strip()
            fid = str(req.get('fileId') or '').strip()
            if not rid:
                raise RuntimeError('batchUpdate 失败：子请求 id 不能为空')
            if rid in seen_ids:
                raise RuntimeError(f'batchUpdate 失败：子请求 id 重复：{rid!r}')
            seen_ids.add(rid)
            if not fid:
                raise RuntimeError(f'batchUpdate 失败：子请求 {rid!r} 缺少 fileId')

            body: Dict[str, Any] = {'fileId': fid}
            name = req.get('name')
            if name is not None and str(name).strip():
                body['name'] = str(name).strip()
            mode = str(req.get('fileRenameMode') or 'force_rename').strip()
            if mode:
                body['fileRenameMode'] = mode
            lo = req.get('localOperatedAt')
            if lo is not None and str(lo).strip():
                body['localOperatedAt'] = str(lo).strip()
            op = req.get('operatorId')
            if op is not None:
                body['operatorId'] = int(op)
            items.append(SubRequest(id=rid, body=body))

        started = time.perf_counter()
        response = dispatcher.personal_saas.batch_update(SubRequestEnvelope(sub_request_list=items))
        finish('richlifeApp/personalSaas/file/batchUpdate', started, response)
        if not response.success:
            raise RuntimeError(f'batchUpdate 失败: {err_message(response, "业务失败")}')

        rows = response.sub_response_list
        if len(rows) != len(items):
            raise RuntimeError('batchUpdate 失败：subResponseList 条数与请求不一致')

        chunk_out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            rid = str(row.id or '').strip()
            if not rid:
                raise RuntimeError('batchUpdate 失败：子响应缺少 id')
            chunk_out[rid] = {
                'code': str(row.code or '').strip(),
                'message': str(row.message or '').strip(),
                'data': row.data,
            }

        if set(chunk_out) != {item.id for item in items}:
            raise RuntimeError('batchUpdate 失败：子响应 id 与请求不一致')
        out.update(chunk_out)

    return out
