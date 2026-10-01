#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 文件/图片行富化与格式化（纯函数，无 manage 卡片配置依赖）。

从 addressDetail / mediaMetaInfo / aiAnalysisInfo 映射出 CLI 展示字段，
并构建图片类输出行。不 import ``CARD_*`` 等 manage config。

用法::

    from mclaw.shared.postprocess.cli_rows import (
        apply_addressline_field,
        apply_semantic_image_ai_analysis_fields,
        format_bytes,
        image_file_record,
        semantic_image_file_record,
    )

    out = image_file_record(row, index=1)
    apply_semantic_image_ai_analysis_fields(out, row)
"""

from __future__ import annotations

from typing import Any

from mclaw.shared.cm_cloud.transforms import cloud_asset_time_to_skill14
from mclaw.shared.cm_cloud.category_token import category_render_token
from mclaw.shared.postprocess.paths import normalize_name_path


def format_bytes(n: int) -> str:
    """将字节数格式化为人类可读的字符串（如 ``1.5MB``）。"""
    for unit, div in (('G', 1 << 30), ('M', 1 << 20), ('K', 1 << 10)):
        if n >= div:
            return f'{n / div:.1f}{unit}B'
    return f'{n}B'


def media_taken_at_from_item(item: dict) -> str:
    """从 File 或富化 row 中提取 ``mediaMetaInfo.takenAt``（或顶层 takenAt）。"""
    if not isinstance(item, dict):
        return ''
    direct = str(item.get('takenAt') or '').strip()
    if direct:
        return direct
    media = item.get('mediaMetaInfo') or {}
    if isinstance(media, dict):
        return str(media.get('takenAt') or '').strip()
    return ''


def format_skill14_time_readable(raw: Any) -> str:
    """将 yyyyMMddHHmmss 转为 ``YYYY-MM-DD HH:MM:SS`` 可读时间。"""
    s = cloud_asset_time_to_skill14(raw)
    if len(s) == 14 and s.isdigit():
        return f'{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}'
    return str(raw or '').strip()


def addressline_for_cli(raw: Any) -> str:
    """从 addressDetail 提取 CLI 展示用的单行地址（addressline）。"""
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        line = raw.get('addressline') or raw.get('addressLine') or ''
        return str(line).strip()
    return ''


def apply_addressline_field(out: dict, row: dict) -> None:
    """CLI 输出地理位置：仅写入 addressline 字符串，不输出完整 addressDetail。"""
    addr = addressline_for_cli(row.get('addressDetail'))
    if addr:
        out['addressline'] = addr


def _aoi_item_name(item: Any) -> str:
    if isinstance(item, dict):
        raw = item.get('name')
    else:
        raw = getattr(item, 'name', None)
    return str(raw).strip() if raw is not None else ''


def _location_aoi_names_for_cli(raw: dict) -> list[str]:
    """从 ``locationAoi`` 列表提取非空 ``name``（去重、保序）。"""
    items = raw.get('locationAoi') or raw.get('location_aoi') or []
    if not isinstance(items, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = _aoi_item_name(item)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def location_names_for_cli(raw: Any) -> list[str]:
    """从 addressDetail 提取 CLI 景点/地标列表（``locationAoi[*].name``）。"""
    if not isinstance(raw, dict):
        return []
    return _location_aoi_names_for_cli(raw)


def apply_location_names_field(out: dict, row: dict) -> None:
    """CLI 输出景点：从 ``addressDetail.locationAoi`` 映射为中文键「景点」。"""
    names = location_names_for_cli(row.get('addressDetail'))
    if names:
        out['景点'] = names


def apply_photo_taken_at_field(out: dict, row: dict) -> None:
    """图片类结果：写入 mediaMetaInfo.takenAt 的可读字段「拍摄时间」。"""
    taken_at = media_taken_at_from_item(row)
    if not taken_at:
        return
    readable_taken_at = format_skill14_time_readable(taken_at)
    if readable_taken_at:
        out['拍摄时间'] = readable_taken_at


def merge_image_ai_analysis_into_base(base: dict, item: dict) -> None:
    """若 ``item`` 含 ``aiAnalysisInfo`` 字典，则原样写入 ``base``（供后续行输出读取）。"""
    info = item.get('aiAnalysisInfo')
    if isinstance(info, dict):
        base['aiAnalysisInfo'] = info


def _extract_thing_label_names(thing_list: list) -> list[str]:
    """从接口 thingLabelList 提取 name 字符串列表。"""
    names: list[str] = []
    for item in thing_list:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            raw = item.get('name')
            name = str(raw).strip() if raw is not None else ''
        else:
            continue
        if name:
            names.append(name)
    return names


def apply_semantic_image_ai_analysis_fields(out: dict, row: dict) -> None:
    """图片 AI 分析：将 aiAnalysisInfo 映射为中文键写入 CLI 输出。"""
    info = row.get('aiAnalysisInfo')
    if not isinstance(info, dict):
        return

    people = info.get('peopleNameList')
    if isinstance(people, list) and people:
        out['人物名称'] = people

    relationships = info.get('relationshipNameList')
    if isinstance(relationships, list) and relationships:
        out['关系称谓'] = relationships

    thing_list = info.get('thingLabelList')
    if isinstance(thing_list, list):
        names = _extract_thing_label_names(thing_list)
        if names:
            out['事物标签'] = names

    face_list = info.get('faceInfoList')
    if isinstance(face_list, list):
        out['人脸数量'] = len(face_list)

    image_quality = info.get('imageQuality')
    if isinstance(image_quality, dict) and 'imgQuality' in image_quality:
        out['图像质量'] = image_quality['imgQuality']

    object_list = info.get('objectList')
    if isinstance(object_list, list) and object_list:
        out['感知物体'] = object_list


def image_file_record(row: dict, *, index: int = 0, with_ai_analysis: bool = False) -> dict:
    """构建图片类卡片数据行（全量字段，不含 record）。"""
    try:
        raw_size = int(row.get('sizeByte') or row.get('size') or 0)
    except (TypeError, ValueError):
        raw_size = 0
    file_path = normalize_name_path(row.get('namePath') or row.get('namepath') or '')

    out: dict[str, Any] = {
        'index': index,
        'fileId': row.get('fileId', ''),
        'parentFileId': str(row.get('parentFileId', '') or ''),
        'name': row.get('name', ''),
        'type': row.get('type', ''),
        'fileExtension': row.get('fileExtension', ''),
        'category': 'image',
        'createdAt': str(row.get('createdAt', '') or ''),
        'updatedAt': str(row.get('updatedAt', '') or ''),
        'size': row.get('size', ''),
        'sizeByte': raw_size,
    }
    if file_path:
        out['filePath'] = file_path
    apply_addressline_field(out, row)
    apply_location_names_field(out, row)
    apply_photo_taken_at_field(out, row)
    if with_ai_analysis:
        apply_semantic_image_ai_analysis_fields(out, row)
    return out


def semantic_image_file_record(row: dict, *, index: int = 0) -> dict:
    """语义搜图用的图片输出行（含 AI 分析字段）。"""
    return image_file_record(row, index=index, with_ai_analysis=True)


def album_image_file_record(row: dict, *, index: int = 0) -> dict:
    """相册图片输出行（不含 AI 分析字段）。"""
    return image_file_record(row, index=index)


def parent_dir_file_path(name_path: str) -> str:
    """由文件全路径 namePath 得到所在目录展示路径（供 filePathList.filePath）。"""
    p = (name_path or '').strip()
    if not p:
        return ''
    i = p.rfind('/')
    if i <= 0:
        return ''
    return p[:i]


def collect_deduped_file_path_entries(enriched_files: list) -> list[dict]:
    """按 (filePath, parentFileId) 去重，生成 filePathList 条目。"""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for row in enriched_files:
        np = str(row.get('namePath') or row.get('namepath') or '').strip()
        is_folder = str(row.get('category') or '').strip().lower() == 'folder'
        if is_folder:
            fp = normalize_name_path(np)
            pfid = str(row.get('fileId') or '').strip()
        else:
            fp = parent_dir_file_path(np)
            pfid = str(row.get('parentFileId') or '').strip()
        key = (fp, pfid)
        if not pfid and not fp:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append({'filePath': fp, 'parentFileId': pfid})
    return out


def enriched_row_to_cli_file_record(row: dict, *, index: int = 0) -> dict:
    """富化行 → fileList / imageList 卡片数据行（全量字段，不含 record）。"""
    raw_name_path = row.get('namePath') or row.get('namepath') or ''
    file_path = normalize_name_path(raw_name_path)
    cat = category_render_token(row.get('category'))
    try:
        raw_size = int(row.get('sizeByte') or 0)
    except (TypeError, ValueError):
        raw_size = 0
    name = row.get('name', '')

    out: dict[str, Any] = {
        'index': index,
        'fileId': row.get('fileId', ''),
        'parentFileId': row.get('parentFileId', ''),
        'name': name,
        'type': row.get('type', ''),
        'fileExtension': row.get('fileExtension', ''),
        'category': cat,
        'createdAt': row.get('createdAt', ''),
        'updatedAt': row.get('updatedAt', ''),
    }
    if file_path:
        out['filePath'] = file_path
    apply_addressline_field(out, row)
    apply_location_names_field(out, row)
    if cat != 'folder':
        out['size'] = row.get('size', '')
        out['sizeByte'] = raw_size
    if cat in ('video', 'audio'):
        out['autoRun'] = row.get('autoRun', False)
        out['duration'] = int(row.get('duration') or 0)
        out['contentSchedule'] = int(row.get('contentSchedule') or 0)

    if cat == 'image':
        apply_photo_taken_at_field(out, row)
        apply_semantic_image_ai_analysis_fields(out, row)

    _handled = frozenset({
        'record', 'index', 'fileId', 'parentFileId', 'name', 'type',
        'fileExtension', 'category', 'createdAt', 'updatedAt',
        'filePath', 'addressDetail', 'addressline', 'size', 'sizeByte',
        'namePath', 'namepath', 'takenAt', 'mediaMetaInfo',
        'autoRun', 'duration', 'contentSchedule',
        'imgUrl', '拍摄时间', 'aiAnalysisInfo', '景点',
        '人物名称', '关系称谓', '事物标签', '人脸数量', '图像质量',
        '图片理解内容', '图片 OCR 文本', '感知物体',
    })
    for key, val in row.items():
        if key not in _handled:
            out[key] = val

    return out


__all__ = [
    'format_bytes',
    'media_taken_at_from_item',
    'format_skill14_time_readable',
    'addressline_for_cli',
    'apply_addressline_field',
    'location_names_for_cli',
    'apply_location_names_field',
    'apply_photo_taken_at_field',
    'merge_image_ai_analysis_into_base',
    'apply_semantic_image_ai_analysis_fields',
    'image_file_record',
    'semantic_image_file_record',
    'album_image_file_record',
    'parent_dir_file_path',
    'collect_deduped_file_path_entries',
    'enriched_row_to_cli_file_record',
]
