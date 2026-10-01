#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云文件富化：路径补全、音视频进度、按 fileId 拉取详情。

供 manage / share 等 skill 共用，禁止 skill 间互引。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from mclaw.shared.cm_cloud.category_token import category_render_token
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.cm_cloud.personal_service import (
    batch_get_all,
    batch_get_path,
    query_file_schedules,
)
from mclaw.shared.postprocess.cli_rows import (
    format_bytes,
    merge_image_ai_analysis_into_base,
)
from mclaw.shared.postprocess.merge_normalize import parse_batch_get_src_file
from mclaw.shared.postprocess.paths import normalize_name_path

_BATCH_MAX = 100


def _clean_name(item: dict) -> str:
    return str(item.get('name', '')).replace('</keywordsTag>', '').replace('<keywordsTag>', '')


def _build_base_item(item: dict, default_cat: str) -> dict:
    size_byte = int(item.get('size', 0) or 0)
    parent_file_id = item.get('parentFileId') or ''
    type_value = str(item.get('type') or '').strip()

    base = {
        'fileId': item.get('fileId', ''),
        'parentFileId': parent_file_id,
        'name': _clean_name(item),
        'namePath': normalize_name_path(item.get('namePath') or item.get('namepath', '')),
        'type': type_value,
        'sizeByte': size_byte,
        'size': format_bytes(size_byte),
        'fileExtension': item.get('fileExtension') or item.get('extension', ''),
        'category': category_render_token(item.get('category', default_cat)),
        'createdAt': item.get('createdAt', ''),
        'updatedAt': item.get('updatedAt', ''),
        'addressDetail': item.get('addressDetail') or {},
    }
    media = item.get('mediaMetaInfo') or {}
    if isinstance(media, dict):
        taken_at = str(media.get('takenAt') or '').strip()
        if taken_at:
            base['takenAt'] = taken_at
    if category_render_token(item.get('category', default_cat)) == 'image':
        merge_image_ai_analysis_into_base(base, item)
    return base


def enrich_media_item(item: dict, schedule: Optional[dict], category: str) -> dict:
    base = _build_base_item(item, category)
    media = dict(item.get('mediaMetaInfo') or {})
    base['mediaMetaInfo'] = media

    try:
        duration_raw = int(float(str(media.get('duration') or 0)))
    except (ValueError, TypeError):
        duration_raw = 0

    media.pop('duration', None)
    if category == 'video':
        media.pop('time', None)
    elif category == 'audio' and duration_raw > 0:
        media['duration'] = duration_raw

    pb_s = is_play = ct = 0
    plt = ''
    if schedule:
        pb_s = int(schedule.get('playbackProgress', 0) or 0)
        is_play = int(schedule.get('isPlay') or 0)
        plt = schedule.get('playLastTime') or ''
        ct = int(schedule.get('contentType') or 0)

    base.update({
        'contentSchedule': pb_s,
        'duration': duration_raw,
        'isPlay': is_play,
        'playLastTime': plt,
        'contentType': ct,
    })
    return base


def enrich_file_list(files: list) -> list:
    media_ids = [
        f.get('fileId') for f in files
        if category_render_token(f.get('category')) in ('video', 'audio') and f.get('fileId')
    ]
    sched_map = query_file_schedules(get_cloud_dispatcher(), media_ids) if media_ids else {}

    result = []
    for f in files:
        cat = category_render_token(f.get('category', ''))
        fid = f.get('fileId')

        if cat in ('video', 'audio'):
            result.append(enrich_media_item(f, sched_map.get(fid), cat))
        elif cat == 'image':
            result.append(_build_base_item(f, 'image'))
        else:
            result.append(_build_base_item(f, cat))
    return result


def hydrate_name_path_for_files(files: list, *, verbose: bool = False) -> list:
    if not files:
        return files

    ids_to_query: list[str] = []
    for item in files:
        fid = item.get('fileId')
        if fid:
            ids_to_query.append(str(fid))

    if not ids_to_query:
        return files

    unique_ids = list(dict.fromkeys(ids_to_query))
    path_map: Dict[str, str] = {}

    try:
        dispatcher = get_cloud_dispatcher()
        for i in range(0, len(unique_ids), _BATCH_MAX):
            chunk = unique_ids[i:i + _BATCH_MAX]
            for row in batch_get_path(dispatcher, chunk):
                if str(row.get('errCode') or '0000') != '0000':
                    continue
                fid = row.get('fileId')
                np = row.get('namePath')
                if fid and np:
                    path_map[str(fid)] = normalize_name_path(np)
    except RuntimeError as exc:
        if verbose:
            print(f'batchGetPath 补全 namePath 失败，已跳过：{exc}', flush=True)
        return files

    if not path_map:
        return files

    for item in files:
        fid = item.get('fileId')
        if not fid:
            continue
        np = path_map.get(str(fid))
        if not np:
            continue
        item['namePath'] = np
        if 'namepath' in item:
            item['namepath'] = np

    return files


def enrich_listing_files(files: list[dict], *, verbose: bool = False) -> list[dict]:
    if not files:
        return []
    hydrated = hydrate_name_path_for_files(files, verbose=verbose)
    return enrich_file_list(hydrated)


def get_enriched_files_by_ids(file_ids: list[str], *, verbose: bool = False) -> list:
    normalized_ids = list(dict.fromkeys(str(fid or '').strip() for fid in file_ids if str(fid or '').strip()))
    if not normalized_ids:
        return []

    dispatcher = get_cloud_dispatcher()
    files: list[dict] = []
    for item in batch_get_all(dispatcher, normalized_ids, thumbnail_styles=['Small']):
        if str(item.get('errCode') or '') != '0000':
            continue
        src_file = parse_batch_get_src_file(item)
        if src_file:
            files.append(src_file)

    if not files:
        return []
    files = hydrate_name_path_for_files(files, verbose=verbose)
    return enrich_file_list(files)


__all__ = [
    'enrich_file_list',
    'enrich_listing_files',
    'get_enriched_files_by_ids',
    'hydrate_name_path_for_files',
]
