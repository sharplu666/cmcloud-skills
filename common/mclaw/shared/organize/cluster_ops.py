#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多维度聚类入口（manage / organize 共用）。

``File`` 来自 ``mclaw.api.search_fusion.File``（Pydantic v2）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from mclaw.api.search_fusion import File
from mclaw.shared.organize.bucket import (
    SUPPORTED_SET_FIELDS,
    UNKNOWN_BUCKET,
    ClusterResult,
    DEFAULT_SET_THRESHOLD,
    build_bucket_fn,
    cluster_one,
    group_by_bucketer,
    distinct_excluding_unknown,
)
from mclaw.shared.organize.bucket.unknown_labels import normalize_bucket_key
from mclaw.shared.organize.bucket.result import bucket_assignment_count


def cluster_single(files: List[File], bucket: str) -> ClusterResult:
    """单维度聚类；set 类桶应用 distinct 阈值。"""
    threshold = DEFAULT_SET_THRESHOLD if bucket in SUPPORTED_SET_FIELDS else None
    return cluster_one(files, bucket, threshold=threshold)


def _first_bucket_key(bucket_name: str, bucketer, file: File) -> str:
    keys = bucketer.bucket_key(file)
    if isinstance(keys, str):
        raw = keys or UNKNOWN_BUCKET
        return normalize_bucket_key(bucket_name, raw)
    for key in keys:
        if key and key != UNKNOWN_BUCKET:
            return normalize_bucket_key(bucket_name, key)
    return normalize_bucket_key(bucket_name, UNKNOWN_BUCKET)


def cluster_cross(files: List[File], buckets: List[str]) -> Dict[str, List[File]]:
    if not buckets:
        raise ValueError('cross 模式至少需要 1 个桶名')
    bucketers = [build_bucket_fn(name) for name in buckets]
    out: Dict[str, List[File]] = {}
    for file in files:
        key = '_'.join(_first_bucket_key(name, bk, file) for name, bk in zip(buckets, bucketers))
        out.setdefault(key, []).append(file)
    return out


def cluster_hierarchical(files: List[File], buckets: List[str]) -> dict:
    if not buckets:
        raise ValueError('hierarchical 模式至少需要 1 个桶名')
    head, *tail = buckets
    grouped = group_by_bucketer(files, head)
    if not tail:
        return grouped
    return {
        name: cluster_hierarchical(bucket_files, tail)
        for name, bucket_files in grouped.items()
    }


def _file_id(file: File) -> str:
    return str(getattr(file, 'file_id', '') or '').strip()


def _unique_file_count(buckets: Dict[str, List[File]]) -> int:
    unique_keys: set[str] = set()
    for bucket_files in buckets.values():
        for file in bucket_files:
            fid = _file_id(file)
            unique_keys.add(fid or f'__object__:{id(file)}')
    return len(unique_keys)


def replace_buckets(result: ClusterResult, buckets: Dict[str, List[File]]) -> ClusterResult:
    return ClusterResult(
        field=result.field,
        granularity=result.granularity,
        buckets=buckets,
        distinct_count=distinct_excluding_unknown(buckets),
        too_many=result.too_many,
        reason=result.reason,
        is_multi_value=result.is_multi_value,
        unique_file_count=_unique_file_count(buckets),
        bucket_assignment_count=bucket_assignment_count(buckets),
    )


def _collect_files(node: Any) -> List[File]:
    if isinstance(node, list):
        return list(node)
    if isinstance(node, dict):
        out: List[File] = []
        for value in node.values():
            out.extend(_collect_files(value))
        return out
    return []


def collect_files_from_buckets(
    *,
    flat: Dict[str, List[File]] | None = None,
    tree: dict | None = None,
) -> List[File]:
    node = flat if flat is not None else tree
    if node is None:
        return []
    raw = _collect_files(node)
    seen: set[str] = set()
    out: List[File] = []
    for file in raw:
        fid = _file_id(file)
        key = fid or f'__object__:{id(file)}'
        if key in seen:
            continue
        seen.add(key)
        out.append(file)
    return out


def flatten_tree(tree: dict, *, prefix: str = '') -> Dict[str, List[File]]:
    out: Dict[str, List[File]] = {}
    for key, value in tree.items():
        name = f'{prefix}_{key}' if prefix else str(key)
        if isinstance(value, list):
            out[name] = list(value)
        else:
            out.update(flatten_tree(value, prefix=name))
    return out


def run_cluster(
    files: List[File],
    *,
    mode: str,
    bucket: str = '',
    buckets: List[str] | None = None,
    all_in_one: bool = False,
    name_all_in_one: str = '',
) -> tuple[Dict[str, List[File]] | None, dict | None]:
    mode = (mode or 'single').strip() or 'single'

    if mode == 'hierarchical':
        tree = cluster_hierarchical(files, list(buckets or []))
        if all_in_one and str(name_all_in_one or '').strip():
            return {str(name_all_in_one).strip(): _collect_files(tree)}, None
        return None, tree

    if mode == 'cross':
        flat = cluster_cross(files, list(buckets or []))
    else:
        if not bucket:
            raise ValueError('single 模式需要 --bucket')
        flat = dict(cluster_single(files, bucket).buckets)

    if all_in_one and str(name_all_in_one or '').strip():
        merged: List[File] = []
        for value in flat.values():
            merged.extend(value)
        return {str(name_all_in_one).strip(): merged}, None
    return flat, None
