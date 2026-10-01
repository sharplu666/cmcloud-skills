#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转存结果富化 + ``:::dynamicList`` 卡（一比一对齐老 query_personal_dynamic 规范）。

卡片契约（docs/business_logic.md §2.7）：无 loadMore 首行、无 index；行键序固定
``{dynamicId, dynamicType, fileId, parentFileId, parentFileName, fileName,
[size, sizeByte,] category, fileExtension, shareText, shareTime}``——
size/sizeByte **仅真实字节数（>0）时输出**（目录 0/富化查不到/空文件省略两键，
不出「0B」噪声）；音视频行（wire category 2/3）追加 ``duration/contentSchedule``；
末行 meta summary 的 n=本页行数。

富化一比一（wire 行只有 contentId/dynamicType/category/type/dynamicTime）：
batchGet（公共库 ``personal_service.batch_get_all`` 宽松逐项：size/sizeByte/
fileExtension/category 文案/parentFileId/name——查不到的项跳过、不殃及整批，
对齐老实现）→ queryFileSchedules（contentSchedule 播放进度 ms）→
getPreviewInfo（duration 秒→ms，仅音视频逐个查）。任一富化失败降级为字段
缺省/空值，不阻断查询（老口径）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from cli_timing import write_cli_output_line
from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas.query_file_schedules_api import (
    QueryFileSchedulesRequest,
)
from mclaw.api.personal_saas.video_preview_api import VideoPreviewRequest
from mclaw.shared.cm_cloud.card import Card
from mclaw.shared.cm_cloud.personal_service import batch_get_all
from mclaw.shared.postprocess.cli_rows import format_bytes
from mclaw.shared.postprocess.merge_normalize import parse_batch_get_src_file

__all__ = [
    'SHARE_TEXT_MAPPING',
    'build_transfer_card_rows',
    'emit_transfer_card',
]

#: dynamicType → 卡片行 shareText（来源文案）
SHARE_TEXT_MAPPING = {5: '分享转存', 6: '圈子转存', 7: '发现转存'}

#: wire category（数字字符串）→ getPreviewInfo 的 category 词形
_PREVIEW_CATEGORY = {'2': 'audio', '3': 'video'}


def _fetch_file_info(dispatcher: ApiDispatcher, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """batchGet 宽松富化 → {fileId: srcFile}；逐项解析，查不到的跳过。"""
    info: Dict[str, Dict[str, Any]] = {}
    if not ids:
        return info
    try:
        for item in batch_get_all(dispatcher, ids):
            parsed = parse_batch_get_src_file(item)
            if not parsed:
                continue
            fid = str(parsed.get('fileId') or '').strip()
            if fid:
                info[fid] = parsed
    except Exception:  # noqa: BLE001 - 富化失败降级（部分已解析的保留）
        pass
    return info


def _fetch_play_schedules(
    dispatcher: ApiDispatcher, av_files: Dict[str, str]
) -> Dict[str, int]:
    """queryFileSchedules → {fileId: 播放进度 ms}；失败降级空映射。"""
    if not av_files:
        return {}
    try:
        resp = dispatcher.personal_saas.query_file_schedules(
            QueryFileSchedulesRequest(
                file_id_list=list(av_files.keys()),
                content_type_list=[int(c) for c in set(av_files.values())],
            )
        )
        if not resp.success:
            return {}
        return {p.file_id: p.playback_progress for p in resp.result_data}
    except Exception:  # noqa: BLE001 - 富化失败降级，不阻断查询
        return {}


def _fetch_duration_map(
    dispatcher: ApiDispatcher, av_files: Dict[str, str]
) -> Dict[str, int]:
    """getPreviewInfo 逐文件 → {fileId: duration ms}；失败/缺时长跳过。"""
    durations: Dict[str, int] = {}
    for fid, cat in av_files.items():
        try:
            resp = dispatcher.personal_saas.video_preview(
                VideoPreviewRequest(
                    file_id=fid,
                    category=_PREVIEW_CATEGORY.get(cat, 'video'),
                )
            )
            if resp.success and resp.duration:
                durations[fid] = int(float(resp.duration) * 1000)
        except Exception:  # noqa: BLE001 - 单文件时长失败跳过
            continue
    return durations


def _size_byte(raw: Any) -> int:
    """size 安全转 int：容忍 int/float/数字字符串（'12.0'），异常兜 0。

    行构造段在富化 try 之外，裸 int() 遇浮点字符串会击穿「富化降级不阻断」。
    """
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        return 0


def build_transfer_card_rows(
    skill_rows: List[Any], dispatcher: ApiDispatcher
) -> List[Dict[str, Any]]:
    """wire 行 + 三步富化 → 卡片行列表（键序固定，对齐老实现）。"""
    ids = [r.content_id for r in skill_rows if r.content_id]
    file_info = _fetch_file_info(dispatcher, ids)

    parent_ids = set()
    for r in skill_rows:
        for pfid in (r.parent_file_id, file_info.get(r.content_id, {}).get('parentFileId', '')):
            pfid = str(pfid or '').strip()
            if pfid and pfid != '/':
                parent_ids.add(pfid)
    parent_names: Dict[str, str] = {}
    if parent_ids:
        parent_infos = _fetch_file_info(dispatcher, list(parent_ids))
        parent_names = {
            fid: str(info.get('name') or '')
            for fid, info in parent_infos.items()
            if info.get('name')
        }

    av_files = {
        r.content_id: r.category
        for r in skill_rows
        if r.category in ('2', '3') and r.content_id
    }
    schedule_map = _fetch_play_schedules(dispatcher, av_files)
    duration_map = _fetch_duration_map(dispatcher, av_files)

    rows: List[Dict[str, Any]] = []
    for r in skill_rows:
        fi = file_info.get(r.content_id, {})
        parent_id = r.parent_file_id or str(fi.get('parentFileId') or '')
        entry: Dict[str, Any] = {
            'dynamicId': r.content_id,
            'dynamicType': r.dynamic_type,
            'fileId': r.content_id,
            'parentFileId': parent_id,
            'parentFileName': parent_names.get(parent_id, ''),
            'fileName': r.name or str(fi.get('name') or ''),
        }
        size_byte = _size_byte(fi.get('size'))
        if size_byte > 0:
            # 仅真实字节数才输出：目录（0）/富化查不到/空文件不出「0B」噪声键
            entry['size'] = format_bytes(size_byte)
            entry['sizeByte'] = size_byte
        entry.update(
            category=str(fi.get('category') or ''),
            fileExtension=str(fi.get('fileExtension') or ''),
            shareText=SHARE_TEXT_MAPPING.get(r.dynamic_type),
            shareTime=r.dynamic_time,
        )
        if r.category in ('2', '3'):
            if r.content_id in duration_map:
                entry['duration'] = duration_map[r.content_id]
            if r.content_id in schedule_map:
                entry['contentSchedule'] = schedule_map[r.content_id]
        rows.append(entry)
    return rows


def emit_transfer_card(card_rows: List[Dict[str, Any]]) -> None:
    """输出 ``:::dynamicList`` 卡（无 header 行；summary 的 n=本页行数）。"""
    summary = f'为您找到{len(card_rows)}个动态'
    for line in Card(
        'dynamicList', card_rows,
        result_type='search', summary=summary, count=len(card_rows),
    ).generate():
        write_cli_output_line(line)
