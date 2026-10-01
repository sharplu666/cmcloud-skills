#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分桶静态卡片与 cluster_profile 展示约束（manage / organize 共用）。"""

from __future__ import annotations

import json
import random
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from mclaw.api.search_fusion import File
from mclaw.shared.cm_cloud.card_meta import build_search_result_summary
from mclaw.shared.organize.bucket.unknown_labels import sort_bucket_keys

CARD_TYPES = {
    'image': 'imageList',
    'file': 'fileList',
}

# 围栏卡末行 ``{"meta":{"resultType":...}}``：中间过程=search，终态结果=generate
RESULT_TYPE_SEARCH = 'search'
RESULT_TYPE_GENERATE = 'generate'

# ``--top`` 分桶静态卡 stdout 最多展示的桶数；与 cluster_profile 示例、plan --bucket-ids 编号对齐
BUCKET_CARD_DISPLAY_LIMIT: int = 5
# 每个分桶静态卡最多展示的数据行数（与 organize PRESEARCH_PREVIEW_LIMIT 一致）
BUCKET_CARD_ROW_LIMIT: int = 10


def card_result_meta_line(
    result_type: str = RESULT_TYPE_SEARCH,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """围栏卡关 ``:::`` 前的 resultType meta 行。

    ``extra`` 的键按传入顺序追加到 ``resultType`` 之后（如 shownByButton / summary）。
    末尾恒追加 ``cardId``：本地时间 mmss + 3 位随机数字（7 位定长，如 0230666）。
    """
    rt = str(result_type or '').strip()
    if rt not in (RESULT_TYPE_SEARCH, RESULT_TYPE_GENERATE):
        raise ValueError(
            f'card_result_meta_line: resultType 仅支持 '
            f'{RESULT_TYPE_SEARCH!r}/{RESULT_TYPE_GENERATE!r}，收到 {result_type!r}'
        )
    meta: Dict[str, Any] = {'resultType': rt}
    if extra:
        meta.update(extra)
    meta['cardId'] = datetime.now().strftime('%M%S') + f'{random.randint(0, 999):03d}'
    return json.dumps(
        {'meta': meta},
        ensure_ascii=False,
    )


def _normalize_file_type(file_type: str = 'image') -> str:
    value = str(file_type or 'image').strip().lower()
    if value not in CARD_TYPES:
        raise ValueError(f'file_type 非法值 {file_type!r}，仅支持 image / file')
    return value


def _card_type(file_type: str = 'image') -> str:
    return CARD_TYPES[_normalize_file_type(file_type)]


def attach_presearch_render_hint(
    payload: Dict[str, Any],
    file_type: str = 'image',
    *,
    bucket_count: int = 0,
    display_bucket_count: int = 0,
    multi_bucket: bool = False,
) -> Dict[str, Any]:
    """为 cluster_profile 去掉 Agent 展示指引字段。

    ``cluster_profile`` 不写 ``renderCards`` / ``renderHint``。
    """
    _ = (file_type, bucket_count, display_bucket_count, multi_bucket)
    out = dict(payload)
    out.pop('renderCards', None)
    out.pop('renderHint', None)
    return out


def attach_profile_render_hint(
    report_line: str,
    *,
    file_type: str,
    top: int = 0,
    bucket_count: int = 0,
    display_bucket_count: int = 0,
) -> dict:
    """聚类统计行附加处理；去掉 ``renderCards`` / ``renderHint``。"""
    payload = json.loads(report_line)
    if int(top or 0) > 0:
        shown = display_bucket_count
        if shown <= 0 and bucket_count > 0:
            shown = min(bucket_count, BUCKET_CARD_DISPLAY_LIMIT)
        payload = attach_presearch_render_hint(
            payload,
            file_type=file_type,
            multi_bucket=bucket_count > 0,
            bucket_count=bucket_count,
            display_bucket_count=shown,
        )
    else:
        payload = attach_presearch_render_hint(payload, file_type=file_type)
    return payload


def _readable_size(n: int) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if n < 1024:
        return f'{n}B'
    if n < 1024 * 1024:
        return f'{n / 1024:.1f}KB'
    if n < 1024 * 1024 * 1024:
        return f'{n / (1024 * 1024):.1f}MB'
    return f'{n / (1024 * 1024 * 1024):.1f}GB'


def file_to_preview_row(file_item: File | Any, *, index: int, file_type: str) -> Dict[str, Any]:
    """File → render_format 规定的六字段行。"""
    category = str(getattr(file_item, 'category', '') or '').strip().lower()
    if not category:
        category = 'image' if file_type == 'image' else 'others'
    try:
        size_val = int(getattr(file_item, 'size', 0) or 0)
    except (TypeError, ValueError):
        size_val = 0
    file_id = getattr(file_item, 'file_id', None) or getattr(file_item, 'fileId', '') or ''
    ext = getattr(file_item, 'file_extension', None) or getattr(file_item, 'fileExtension', '') or ''
    return {
        'index': index,
        'name': str(getattr(file_item, 'name', '') or ''),
        'fileId': str(file_id),
        'size': _readable_size(size_val),
        'category': category,
        'fileExtension': str(ext).lower(),
    }


def format_bucket_overflow_notice(total: int, shown: int) -> str:
    """桶数超出展示上限时，写在第一张卡 ``meta.summary`` 前的提示。"""
    return f'总共{int(total)}个分类，下面只展示其中的{int(shown)}个分类。'


def format_bucket_card_title(bucket_name: str) -> str:
    """分桶静态卡标题：桶 key 直出；``UNKNOWN``→「未分类」，``ALL``→「全部」。"""
    name = str(bucket_name or '').strip()
    if name == 'UNKNOWN':
        return '未分类'
    if name == 'ALL':
        return '全部'
    return name


def build_bucket_card_title_formatter(
    *,
    file_type: str = 'image',
    top: int = 0,
    bucket_map: Mapping[str, Sequence[Any]] | None = None,
    rows_per_bucket: int = BUCKET_CARD_ROW_LIMIT,
    bucket_title_fn: Callable[[str], str] | None = None,
    phase: str | None = None,
) -> Callable[[str], str]:
    """构造 ``iter_bucket_grouped_card_lines`` 可用的 ``title_formatter``。"""
    title_fn = bucket_title_fn or format_bucket_card_title
    caps = max(int(rows_per_bucket or 0), 0)
    buckets = bucket_map or {}

    def _formatter(bucket_name: str) -> str:
        files = list(buckets.get(bucket_name) or [])
        shown = min(len(files), caps) if caps else len(files)
        return build_search_result_summary(
            file_type=file_type,
            total=len(files),
            shown=shown,
            top=top,
            bucket_name=title_fn(bucket_name),
            phase=phase,
        )

    return _formatter


def count_bucket_card_display_rows(
    bucket_map: Dict[str, List[Any]],
    *,
    bucket_limit: int = BUCKET_CARD_DISPLAY_LIMIT,
    rows_per_bucket: int = BUCKET_CARD_ROW_LIMIT,
) -> int:
    """stdout 分桶静态卡实际数据行数（桶上限 × 每桶行上限之后）。"""
    display = buckets_for_card_display(bucket_map, limit=bucket_limit)
    row_cap = max(int(rows_per_bucket or 0), 0)
    total = 0
    for files in display.values():
        n = len(files)
        total += min(n, row_cap) if row_cap else n
    return total


def render_static_card(
    *,
    file_type: str,
    rows: List[Dict[str, Any]],
    summary: Optional[str] = None,
) -> str:
    """无 loadMore/searchParam 首行的卡片块（预览态，resultType=search）。

    内部经 ``Card`` 组装（单一组装路径）；cardId 仍由 ``card_result_meta_line`` 注入。
    """
    from mclaw.shared.cm_cloud.card import Card

    card_type = _card_type(file_type)
    summary_text = str(summary or '').strip()
    return '\n'.join(
        Card(
            card_type,
            rows,
            header=None,
            summary=summary_text or None,
            result_type=RESULT_TYPE_SEARCH,
        ).generate()
    )


def flatten_bucket_tree(tree: dict, prefix: str = '') -> Dict[str, List[Any]]:
    """层级聚类树 → 叶子桶名 → 文件列表。"""
    out: Dict[str, List[Any]] = {}

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            if node:
                out[path or 'UNKNOWN'] = node
            return
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f'{path}/{key}' if path else str(key)
                _walk(child, child_path)

    _walk(tree, prefix)
    return out


def collect_non_empty_buckets(
    *,
    flat: Optional[Dict[str, List[Any]]] = None,
    tree: Optional[dict] = None,
) -> Dict[str, List[Any]]:
    """合并 flat / hierarchical 产物，仅保留非空桶；UNKNOWN 排在末尾。"""
    buckets: Dict[str, List[Any]] = dict(flat or {})
    if tree is not None:
        buckets.update(flatten_bucket_tree(tree))
    non_empty = {k: v for k, v in buckets.items() if v}
    ordered = sort_bucket_keys(non_empty)
    return {k: non_empty[k] for k in ordered}


def ordered_bucket_names(bucket_map: Dict[str, List[Any]]) -> List[str]:
    """非空桶名列表（``sort_bucket_keys`` 顺序，与 plan ``--bucket-ids`` 编号一致）。"""
    non_empty = {k: v for k, v in bucket_map.items() if v}
    return sort_bucket_keys(non_empty)


def buckets_for_card_display(
    bucket_map: Dict[str, List[Any]],
    *,
    limit: int = BUCKET_CARD_DISPLAY_LIMIT,
) -> Dict[str, List[Any]]:
    """stdout 分桶静态卡用的桶子集（最多 ``limit`` 个，顺序与 ``ordered_bucket_names`` 一致）。"""
    names = ordered_bucket_names(bucket_map)
    if limit > 0 and len(names) > limit:
        names = names[:limit]
    non_empty = {k: v for k, v in bucket_map.items() if v}
    return {name: non_empty[name] for name in names}


def iter_bucket_grouped_card_lines(
    buckets: Dict[str, List[Any]],
    *,
    file_type: str = 'image',
    title_formatter: Optional[Callable[[str], str]] = None,
    rows_per_bucket: int = BUCKET_CARD_ROW_LIMIT,
    top: int = 0,
    phase: Optional[str] = None,
    limit: int = BUCKET_CARD_DISPLAY_LIMIT,
    total_bucket_count: Optional[int] = None,
):
    """逐行产出分桶静态卡 stdout：卡片块各行（无块前标题）。

    ``top>0`` 且未传 ``title_formatter`` 时，用精选文案写入块末 ``meta.summary``
    （``已从搜索结果中（{桶}分类）精选出…``；``phase='plan'`` 则为规划结果）；
    否则 ``summary`` 为桶名。
    桶数超出 ``limit`` 时，第一张卡 ``summary`` 前追加
    ``总共x个分类，下面只展示其中的limit个分类。``
    每桶最多 ``rows_per_bucket`` 行数据（默认 ``BUCKET_CARD_ROW_LIMIT``）。
    调用方应传入完整桶表；本函数按 ``limit`` 截断（默认最多 5 桶）。
    ``total_bucket_count`` 仅在调用方已截断时用于提示总数。
    """
    names = ordered_bucket_names(buckets)
    total = len(names) if total_bucket_count is None else max(int(total_bucket_count), 0)
    display_limit = max(int(limit or 0), 0)
    truncated = display_limit > 0 and total > display_limit
    if title_formatter is None and int(top or 0) > 0:
        title_formatter = build_bucket_card_title_formatter(
            file_type=file_type,
            top=top,
            bucket_map=buckets,
            rows_per_bucket=rows_per_bucket,
            phase=phase,
        )
    fmt_title = title_formatter or format_bucket_card_title
    row_cap = max(int(rows_per_bucket or 0), 0)
    if display_limit > 0 and len(names) > display_limit:
        buckets = buckets_for_card_display(buckets, limit=display_limit)
    first = True
    for bucket_name in ordered_bucket_names(buckets):
        files = buckets[bucket_name]
        if row_cap:
            files = files[:row_cap]
        rows = [
            file_to_preview_row(file_item, index=idx, file_type=file_type)
            for idx, file_item in enumerate(files, start=1)
        ]
        if rows:
            title = fmt_title(bucket_name)
            summary = title
            if first and truncated:
                summary = f'{format_bucket_overflow_notice(total, display_limit)}\n{title}'
            first = False
            yield from render_static_card(
                file_type=file_type,
                rows=rows,
                summary=summary,
            ).splitlines()


def render_bucket_grouped_cards(
    buckets: Dict[str, List[Any]],
    *,
    file_type: str = 'image',
    limit: int = BUCKET_CARD_DISPLAY_LIMIT,
    title_formatter: Optional[Callable[[str], str]] = None,
    top: int = 0,
    phase: Optional[str] = None,
) -> str:
    """每个分桶一个静态卡片块（无 loadMore 首行、无块前标题）。

    传入完整桶表；超出 ``limit`` 时只渲染前 ``limit`` 张，并在第一张卡
    ``meta.summary`` 前追加总数提示。
    """
    return '\n'.join(
        iter_bucket_grouped_card_lines(
            buckets,
            file_type=file_type,
            title_formatter=title_formatter,
            top=top,
            phase=phase,
            limit=limit,
        )
    )
