#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云常用编排（batchGet / taskGet）——供各 skill 共用，禁止 skill 间互引。

依赖运行时 ``sys.path`` 已含 ``common_auth``（``cli_trace``）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas.batch_get_api import BatchGetRequest
from mclaw.api.personal_saas.get_path_api import GetPathRequest
from mclaw.api.personal_saas.query_file_schedules_api import QueryFileSchedulesRequest
from mclaw.api.search.get_async_task_status_api import GetAsyncTaskStatusRequest
from mclaw.shared.cm_cloud.transforms import parse_playback_milliseconds
from mclaw.shared.postprocess.api_obs import data_dict, err_message, finish

_BATCH_MAX = 100
_QUERY_SCHEDULES_MAX = 200


def batch_get(
    dispatcher: ApiDispatcher,
    file_ids: List[str],
    thumbnail_styles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """批量获取个人云文件详情。失败抛 RuntimeError。"""
    request = BatchGetRequest(file_ids=list(file_ids), thumbnail_style_list=thumbnail_styles)
    response = dispatcher.personal_saas.batch_get(request)
    finish('richlifeApp/personalSaas/file/batchGet', 0.0, response)
    if str(response.code or '') != '0000':
        msg = str(getattr(response, 'message', '') or '').strip() or '业务失败'
        raise RuntimeError(f'batchGet 失败: {msg}')
    return ((getattr(response, 'raw', None) or {}).get('data') or {}).get('batchFileResults') or []


def batch_get_all(
    dispatcher: ApiDispatcher,
    file_ids: List[str],
    thumbnail_styles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """分片调用 batchGet，合并 batchFileResults。"""
    normalized = list(dict.fromkeys(str(fid or '').strip() for fid in file_ids if str(fid or '').strip()))
    results: List[Dict[str, Any]] = []
    for offset in range(0, len(normalized), _BATCH_MAX):
        chunk = normalized[offset: offset + _BATCH_MAX]
        results.extend(batch_get(dispatcher, chunk, thumbnail_styles=thumbnail_styles))
    return results


def batch_get_path(dispatcher: ApiDispatcher, file_ids: List[str]) -> List[Dict[str, Any]]:
    """批量获取文件全路径信息。返回原始 items；失败抛 RuntimeError。"""
    if not file_ids:
        return []
    request = GetPathRequest(file_ids=list(file_ids))
    response = dispatcher.personal_saas.get_path(request)
    finish('richlifeApp/personalSaas/file/batchGetPath', 0.0, response)
    if str(response.code or '') != '0000':
        raise RuntimeError(f'batchGetPath 失败: {err_message(response, "业务失败")}')
    return data_dict(response).get('items') or []


def query_file_schedules(
    dispatcher: ApiDispatcher,
    file_ids: List[str],
    content_type_list: Optional[List[int]] = None,
) -> Dict[str, Dict[str, Any]]:
    """按文件 ID 查询音视频播放进度。返回 {fileId: {...}}。"""
    ids = [x for x in file_ids if x]
    if not ids:
        return {}
    ct = content_type_list if content_type_list is not None else [2, 3]
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), _QUERY_SCHEDULES_MAX):
        chunk = ids[i: i + _QUERY_SCHEDULES_MAX]
        request = QueryFileSchedulesRequest(file_id_list=chunk, content_type_list=ct)
        try:
            response = dispatcher.personal_saas.query_file_schedules(request)
            finish('richlifeApp/personalDynamic/queryFileSchedules', 0.0, response)
        except RuntimeError:
            continue
        if not response.success:
            continue
        for row in response.result_data:
            if not row.file_id:
                continue
            out[row.file_id] = {
                'playbackProgress': parse_playback_milliseconds(row.playback_progress),
                'isPlay': int(row.is_play or 0),
                'playLastTime': row.play_last_time or '',
                'contentType': int(row.content_type or 0),
                'id': row.id,
            }
    return out


def task_get(dispatcher: ApiDispatcher, task_id: str) -> Optional[Dict[str, Any]]:
    """查询个人云异步任务状态。失败静默返回 None。"""
    try:
        response = dispatcher.search.get_async_task_status(
            GetAsyncTaskStatusRequest(task_id=task_id)
        )
        finish('richlifeApp/personalSaas/task/get', 0.0, response)
    except RuntimeError:
        return None
    if str(response.code or '') != '0000':
        return None
    return (getattr(response, 'raw', None) or {}).get('data') or {}


__all__ = ['batch_get', 'batch_get_all', 'batch_get_path', 'query_file_schedules', 'task_get']
