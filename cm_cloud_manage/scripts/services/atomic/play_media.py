#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""播放原子能力 —— 按 fileId 取播放数据并组装单条卡片条目。

``build_play_media_entry``：batch_get 取权威 ``category`` 校验是否视频/音频 →
补全播放进度与时长 → 返回 ``autoRun=true`` 条目 dict；回执（ok_meta）与卡片输出
在 CLI 层（cli/play_media.py）。时长沿用 ``getPreviewInfo`` 裸 HTTP（公共库无该
封装），用公共库 ``get_skill_auth()`` 取 host / 鉴权头；进度走公共库
``query_file_schedules``。
"""

from __future__ import annotations

from typing import Any, Dict

import requests

from mclaw.api.auth import get_skill_auth
from mclaw.api.personal_saas.batch_get_api import BatchGetRequest
from mclaw.api.app_endpoint_map import resolve_url
from mclaw.shared.cm_cloud.category_token import category_render_token
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.cm_cloud.personal_service import query_file_schedules
from mclaw.shared.postprocess.api_obs import err_message
from mclaw.shared.postprocess.cli_rows import format_bytes
from services.errors import OperationServiceError, wrap_api_error

# 英文 content_type → 后端 contentType 数字（query_file_schedules 用；不暴露 CLI）
_CT_NUM: Dict[str, int] = {'audio': 2, 'video': 3}

#: ``getPreviewInfo`` 路径（原实现同款裸 HTTP）
_PREVIEW_PATH = '/richlifeApp/personalSaas/videoPreview/getPreviewInfo'


def build_play_media_entry(file_id: str, content_type: str) -> Dict[str, Any]:
    """按 fileId 组装播放条目：详情校验 → 进度 → 时长（后两者非致命，失败落 0）。"""
    src = _fetch_and_check_category(file_id, content_type)
    content_schedule = _fetch_schedule(file_id, content_type)
    duration_ms = _fetch_duration(file_id, content_type)

    size_byte = int(src.get('size') or 0)
    return {
        'index': 1,
        'fileId': file_id,
        'name': str(src.get('name') or ''),
        'size': format_bytes(size_byte),
        'sizeByte': size_byte,
        'fileExtension': str(src.get('fileExtension') or ''),
        'category': content_type,
        'duration': duration_ms,
        'contentSchedule': content_schedule,
        'autoRun': True,
    }


# ── batch_get：取详情 + 校验 category（正反例核心） ──

def _fetch_and_check_category(file_id: str, expect: str) -> Dict[str, Any]:
    request = BatchGetRequest(file_ids=[file_id], thumbnail_style_list=['Small'])
    try:
        response = get_cloud_dispatcher().personal_saas.batch_get(request)
    except RuntimeError as exc:
        raise wrap_api_error(exc, '查询详情') from exc
    if not (response.success and str(response.code or '') == '0000'):
        raise OperationServiceError(
            f'查询详情失败：{err_message(response, "业务失败")}；请停止并交用户决策，勿自动重试'
        )

    results = list(response.batch_file_results or [])
    item = results[0] if results else None
    if item is None or str(item.err_code or '0000') != '0000' or item.src_file is None:
        raise OperationServiceError(
            f'播放失败：未找到该 fileId（batchGet 返回空）；请确认 fileId={file_id} 是否正确'
        )
    src = getattr(item.src_file, 'raw', None) or item.src_file.model_dump(
        by_alias=True, mode='json'
    )

    actual = category_render_token(src.get('category'))
    if actual != expect:
        raise OperationServiceError(
            f'文件类型不匹配：--content-type 要求 category={expect}，'
            f'但该 fileId 实际 category={actual}；请核对 fileId 与文件类型后重试'
        )
    return src


# ── 播放进度（非致命：异常落 0，不阻塞播放） ──

def _fetch_schedule(file_id: str, content_type: str) -> int:
    try:
        sched_map = query_file_schedules(
            get_cloud_dispatcher(), [file_id], content_type_list=[_CT_NUM[content_type]]
        )
    except Exception as exc:  # noqa: BLE001 非致命
        print(f'查询播放进度失败（{file_id}）: {exc}', flush=True)
        return 0
    try:
        return int(sched_map.get(file_id, {}).get('playbackProgress', 0) or 0)
    except (TypeError, ValueError):
        return 0


# ── 时长（原实现同款 getPreviewInfo 裸 HTTP；非致命） ──

def _fetch_duration(file_id: str, content_type: str) -> int:
    auth = get_skill_auth()
    url = resolve_url(auth.host, _PREVIEW_PATH)
    try:
        resp = requests.post(
            url,
            json={'fileId': file_id, 'category': content_type},
            headers=auth.get_common_header(),
            timeout=30,
        )
        if resp.status_code != 200:
            print(f'获取时长失败（{file_id}）: HTTP {resp.status_code}', flush=True)
            return 0
        result = resp.json()
    except Exception as exc:  # noqa: BLE001 非致命
        print(f'获取时长失败（{file_id}）: {exc}', flush=True)
        return 0
    if not (result.get('success') and result.get('code') == '0000'):
        print(f'获取时长失败（{file_id}）: {result.get("message")}', flush=True)
        return 0
    data = result.get('data') or {}
    meta = data.get('meta') or {}
    dur = meta.get('duration', '')
    if dur in ('', None):
        return 0
    try:
        return int(float(dur) * 1000)  # 秒 → 毫秒
    except (TypeError, ValueError):
        print(f'duration 解析失败（{file_id}）: {dur!r}', flush=True)
        return 0


__all__ = ['build_play_media_entry']
