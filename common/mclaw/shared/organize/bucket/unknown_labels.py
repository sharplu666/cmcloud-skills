#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺失维度桶的展示名：按聚类字段映射为中文标签（不再使用 ``UNKNOWN`` 字面量）。"""

from __future__ import annotations

from typing import Dict, Iterable, List

from mclaw.shared.organize.bucket.base import UNKNOWN_BUCKET

UNKNOWN_LABEL_TIME = '未知时间'
UNKNOWN_LABEL_LOCATION = '未知位置'
UNKNOWN_LABEL_TYPE = '未知类型'
UNKNOWN_LABEL_RELATIONSHIP = '未知关系'
UNKNOWN_LABEL_PEOPLE = '未知人物'
UNKNOWN_LABEL_FACE_COUNT = '未知人脸数量'
UNKNOWN_LABEL_THING = '未知事物'

_UNKNOWN_LABEL_BY_BUCKET: Dict[str, str] = {
    'day': UNKNOWN_LABEL_TIME,
    'week': UNKNOWN_LABEL_TIME,
    'month': UNKNOWN_LABEL_TIME,
    'year': UNKNOWN_LABEL_TIME,
    'uploadMonth': UNKNOWN_LABEL_TIME,
    'uploadYear': UNKNOWN_LABEL_TIME,
    'location': UNKNOWN_LABEL_LOCATION,
    'country': UNKNOWN_LABEL_LOCATION,
    'province': UNKNOWN_LABEL_LOCATION,
    'city': UNKNOWN_LABEL_LOCATION,
    'district': UNKNOWN_LABEL_LOCATION,
    'township': UNKNOWN_LABEL_LOCATION,
    'locationNames': UNKNOWN_LABEL_LOCATION,
    'locationAoi': UNKNOWN_LABEL_LOCATION,
    'objectList': UNKNOWN_LABEL_LOCATION,
    'category': UNKNOWN_LABEL_TYPE,
    'fileExtension': UNKNOWN_LABEL_TYPE,
    'livePhoto': UNKNOWN_LABEL_TYPE,
    'faceGroup': UNKNOWN_LABEL_TYPE,
    'relationshipNameList': UNKNOWN_LABEL_RELATIONSHIP,
    'peopleNameList': UNKNOWN_LABEL_PEOPLE,
    'faceCount': UNKNOWN_LABEL_FACE_COUNT,
    'thingLabelList': UNKNOWN_LABEL_THING,
}

_CATEGORY_FALLBACK: Dict[str, str] = {
    'time': UNKNOWN_LABEL_TIME,
    'location': UNKNOWN_LABEL_LOCATION,
    'attr': UNKNOWN_LABEL_TYPE,
}

ALL_UNKNOWN_BUCKET_LABELS = frozenset({
    UNKNOWN_BUCKET,
    *_UNKNOWN_LABEL_BY_BUCKET.values(),
})


def unknown_bucket_label(bucket_name: str) -> str:
    """按聚类字段名返回缺失值桶的展示名。"""
    explicit = _UNKNOWN_LABEL_BY_BUCKET.get(str(bucket_name or '').strip())
    if explicit:
        return explicit
    try:
        from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY

        cls = BUCKET_REGISTRY.get_class(bucket_name)
        if bucket_name == 'faceCount':
            return UNKNOWN_LABEL_FACE_COUNT
        return _CATEGORY_FALLBACK.get(cls.bucket_category, UNKNOWN_LABEL_TYPE)
    except ValueError:
        return UNKNOWN_LABEL_TYPE


def normalize_bucket_key(bucket_name: str, key: str) -> str:
    """将 ``UNKNOWN`` 字面量替换为当前维度的中文缺失桶名。"""
    if key != UNKNOWN_BUCKET:
        return key
    return unknown_bucket_label(bucket_name)


def is_unknown_bucket_key(key: str) -> bool:
    """是否为缺失维度桶名（含历史 ``UNKNOWN`` 与各维度中文标签）。"""
    return str(key or '').strip() in ALL_UNKNOWN_BUCKET_LABELS


def sort_bucket_keys(keys: Iterable[str]) -> List[str]:
    """桶名排序：普通桶升序，缺失维度桶排在末尾。"""
    keys_list = list(keys)
    regular = sorted(k for k in keys_list if not is_unknown_bucket_key(k))
    unknowns = sorted(k for k in keys_list if is_unknown_bucket_key(k))
    return regular + unknowns


def unknown_bucket_file_count(buckets: Dict[str, list]) -> int:
    """统计所有缺失维度桶内的文件数。"""
    return sum(len(files) for key, files in buckets.items() if is_unknown_bucket_key(key))
