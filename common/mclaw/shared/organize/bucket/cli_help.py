#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``--bucket`` / ``--buckets`` CLI 帮助文案（由 ``BUCKET_REGISTRY`` 派生，与代码注册一致）。"""

from __future__ import annotations

# 与 bucket/__init__.py 相同：逐模块 import 触发 @register_bucket（避免经 __init__ 循环导入）
from mclaw.shared.organize.bucket import all_bucket  # noqa: F401
from mclaw.shared.organize.bucket import category_bucket  # noqa: F401
from mclaw.shared.organize.bucket import face_count_bucket  # noqa: F401
from mclaw.shared.organize.bucket import face_group_bucket  # noqa: F401
from mclaw.shared.organize.bucket import file_extension_bucket  # noqa: F401
from mclaw.shared.organize.bucket import live_photo_bucket  # noqa: F401
from mclaw.shared.organize.bucket import location_bucket  # noqa: F401
from mclaw.shared.organize.bucket import set_field_bucket  # noqa: F401
from mclaw.shared.organize.bucket import time_bucket  # noqa: F401

from mclaw.shared.organize.bucket.discovery import list_categories
from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY

#: 当前已注册桶名（字母序），与 ``BUCKET_REGISTRY.build(name)`` 合法入参一致。
REGISTERED_BUCKET_NAMES: tuple[str, ...] = tuple(sorted(BUCKET_REGISTRY))

_CLUSTERING_RULES_REF = '规则见 cm_cloud_organize/CLUSTERING-RULES.md'


def format_registered_bucket_names(*, separator: str = ', ') -> str:
    return separator.join(REGISTERED_BUCKET_NAMES)


def format_bucket_catalog_short() -> str:
    """按分类汇总已注册桶名（用于 argparse help）。"""
    parts: list[str] = []
    for cat in list_categories():
        members = '/'.join(cat.members)
        if cat.default:
            parts.append(f'{cat.name}(默认{cat.default}): {members}')
        else:
            parts.append(f'{cat.name}: {members}')
    return ' | '.join(parts)


_BUCKET_NAMES_ALL = format_registered_bucket_names()

HELP_ORGANIZE_MODE = (
    'single=单维度（默认）；'
    'cross=多维度组合键平铺（输出 cluster_profile）；'
    'hierarchical=多维度层级嵌套（输出 cluster_hierarchical_profile）'
)

# -h 只列字母序全集，避免再堆一层「分类默认」长串（可读性）；全集须保留供合法入参核对与单测。
HELP_BUCKET_VALUE_BASE = (
    f'须传已注册桶名：{_BUCKET_NAMES_ALL}。'
    '勿传分类别名 time/location；'
    f'{_CLUSTERING_RULES_REF}'
)

HELP_ORGANIZE_BUCKET_SINGLE_PRESEARCH = (
    'single 模式：' + HELP_BUCKET_VALUE_BASE + '；不传则不分桶，仅输出全量预览'
)

HELP_ORGANIZE_BUCKET_SINGLE_PLAN = (
    'single 模式必填：' + HELP_BUCKET_VALUE_BASE
)

HELP_ORGANIZE_BUCKET_SINGLE_MEMORY = (
    'single 模式可选：' + HELP_BUCKET_VALUE_BASE + '；省略则整集去重后处理'
)

HELP_ORGANIZE_BUCKET_SINGLE_ARCHIVE = (
    'single 模式：' + HELP_BUCKET_VALUE_BASE + '；归档常用 category/fileExtension'
)

HELP_ORGANIZE_BUCKETS = (
    'cross/hierarchical：逗号分隔已注册桶名，如 month,city；'
    '合法名同 --bucket（'
    + _BUCKET_NAMES_ALL
    + '）；勿传分类别名 time/location；'
    + _CLUSTERING_RULES_REF
)

HELP_MANAGE_CLUSTER_BUCKET = (
    '按单一维度聚类预览（manage 仅支持 --bucket，无 --mode/--buckets/--all-in-one）。'
    '合法桶名：'
    + _BUCKET_NAMES_ALL
    + '。勿传分类别名 time/location；'
    + _CLUSTERING_RULES_REF
    + '。启用后先拉全量再分桶，与 --page-cursor 互斥'
)
