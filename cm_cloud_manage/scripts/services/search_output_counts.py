#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索 CLI 计数与摘要文案（统一 ``totalCount`` / ``counts`` 语义）。"""

from __future__ import annotations

from typing import Any, Dict

__all__ = [
    'apply_search_counts_to_meta',
    'build_search_counts',
    'format_flat_top_message',
]


def build_search_counts(
    *,
    search_hits: int,
    displayed: int,
    after_select_filter: Optional[int] = None,
    saved_reuse: Optional[int] = None,
    saved_plan: Optional[int] = None,
) -> Dict[str, int]:
    """构建 ``meta.counts``。

    - ``searchHits``：云端检索命中（去重前 API 总量）
    - ``afterSelectFilter``：``--top`` / ``--dedup`` 管线去重后（``--top`` 另含标签过滤；分桶前）
    - ``displayed``：本次 stdout 实际展示条数（**即最终答案**）
    - ``savedReuse`` / ``savedPlan``：落盘 jsonl 条数（规划交接用）
    """
    counts: Dict[str, int] = {
        'searchHits': int(search_hits),
        'displayed': int(displayed),
    }
    if after_select_filter is not None:
        counts['afterSelectFilter'] = int(after_select_filter)
    if saved_reuse is not None:
        counts['savedReuse'] = int(saved_reuse)
    if saved_plan is not None:
        counts['savedPlan'] = int(saved_plan)
    return counts


def format_flat_top_message(
    *,
    search_hits: int,
    displayed: int,
    after_select_filter: Optional[int] = None,
) -> str:
    """非聚类 ``--top`` 模式摘要。"""
    if after_select_filter is not None and after_select_filter != search_hits:
        lead = f'检索命中 {search_hits} 条，精选去重后 {after_select_filter} 条'
    else:
        lead = f'检索命中 {search_hits} 条'
    return f'{lead}；展示 {displayed} 条'


def apply_search_counts_to_meta(
    meta: Dict[str, Any],
    counts: Dict[str, int],
    *,
    include_api_total: bool = False,
) -> None:
    """写入 ``counts``；``totalCount`` 须由调用方设为 ``counts['displayed']``。"""
    meta['counts'] = counts
    if include_api_total:
        meta['apiTotalCount'] = counts['searchHits']
