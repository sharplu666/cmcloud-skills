#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚类结果数据结构 + 分组工具。

本模块是 bucket 包的「分组统计层」，与各 ``xxx_bucket.py``（字段提取层）配合：

    File 列表
        │
        │ 各 xxx_bucket.Bucketer.bucket_key(f) → '2026-05' / '深圳市' / ['磊磊']
        ↓
    _group_by_bucketer(files, bucket_name) → dict[str, list[File]]
        │
        │ 统计 distinct 数 + too_many 检测
        ↓
    ClusterResult

ClusterResult 再交给 ``bucket.profile.format_cluster_report`` 输出给 agent，
或 ``bucket.profile.cluster_one`` / ``profile_all_dimensions`` 调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.registry import build_bucket_fn
from mclaw.shared.organize.bucket.unknown_labels import (
    is_unknown_bucket_key,
    normalize_bucket_key,
)


#: set 聚类「类别过多」阈值；与 feishu_album_doc.md 长尾硬上限一致。
#:
#: 原 ``cm_cloud_organize`` 版本从 ``manage_bootstrap.load_organize_settings()``
#: 读取 ``CLUSTER_SET_THRESHOLD``（默认 30）。本共享模块不依赖 organize 的
#: ``config.py``，直接固化常量 30；如需覆盖，调用方可在构造 ``cluster_one``
#: 时显式传 ``threshold``。
DEFAULT_SET_THRESHOLD: int = 30


@dataclass(frozen=True)
class ClusterResult:
    """聚类结果。``too_many=True`` 表示类别数超阈值，调用方不应以此维度整理。

    Attributes:
        field: 聚类字段名（time / city / set 子字段名 / 任意已注册桶名）
        granularity: 时间粒度（仅 day/week/month/year 桶有值）
        buckets: ``{桶名: [File]}``，UNKNOWN 桶保持原字面量 ``UNKNOWN_BUCKET``
        distinct_count: 去除 UNKNOWN 后的 distinct 桶数
        too_many: ``distinct_count > threshold`` 时为 True
        reason: ``too_many=True`` 时的告知文案
        is_multi_value: 是否多值桶（一个 file 可进多个桶）
        unique_file_count: 参与聚类的唯一文件数
        bucket_assignment_count: 各桶文件数之和（多值桶可大于 unique_file_count）
    """

    field: str
    granularity: str = ''
    buckets: Dict[str, List[File]] = field(default_factory=dict)
    distinct_count: int = 0
    too_many: bool = False
    reason: str = ''
    is_multi_value: bool = False
    unique_file_count: int = 0
    bucket_assignment_count: int = 0


def group_by_bucketer(files: List[File], bucket_name: str) -> Dict[str, List[File]]:
    """通用分组：单值桶返回 str，多值桶返回 list[str]，统一处理。

    UNKNOWN 桶保持原 ``UNKNOWN_BUCKET`` 字面量。

    Args:
        files: 待分组的 File 列表
        bucket_name: 已在 ``BUCKET_REGISTRY`` 注册的桶名

    Returns:
        ``{桶名: [File]}``；单值桶每个 file 进一个桶，多值桶可进多个
    """
    bucketer = build_bucket_fn(bucket_name)
    buckets: Dict[str, List[File]] = {}
    for f in files:
        keys = bucketer.bucket_key(f)
        if isinstance(keys, str):
            keys = [keys]
        for key in keys:
            nk = normalize_bucket_key(bucket_name, key)
            buckets.setdefault(nk, []).append(f)
    return buckets


def distinct_excluding_unknown(buckets: Dict[str, List[File]]) -> int:
    """统计 distinct 桶数（排除缺失维度桶）。"""
    return len([k for k in buckets if not is_unknown_bucket_key(k)])


def bucket_assignment_count(buckets: Dict[str, List[File]]) -> int:
    """各桶文件数之和（多值桶下可大于唯一文件数）。"""
    return sum(len(v) for v in buckets.values())
