#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚类入口 + 多维度画像 + 输出格式化。

依赖 ``bucket.result`` 提供的 ``ClusterResult`` / ``group_by_bucketer`` /
``distinct_excluding_unknown``，以及 ``bucket.registry.BUCKET_REGISTRY``。

公开 API：

单维度：

- ``cluster_one(files, bucket_name, threshold=None) → ClusterResult``
    通用单维度聚类入口（替代具名 clusterer 类）
- ``profile_all_dimensions(files, *, time_granularity, set_threshold) → dict``
    数据驱动扫描所有已注册分类的默认桶，生成画像
- ``format_cluster_report(result) → str``
    格式化为 ``cluster_profile`` JSON 行

多维度（可视化，聚类逻辑由调用方完成）：

- ``format_cross_report(buckets_spec, bucket_map) → str``
    交叉聚类（平铺）结果 → ``cluster_profile`` JSON 行
- ``format_hierarchical_report(buckets_spec, tree) → str``
    层级聚类（嵌套）结果 → ``cluster_hierarchical_profile`` JSON 行（嵌套 dict）
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY
from mclaw.shared.organize.bucket.unknown_labels import (
    sort_bucket_keys,
    unknown_bucket_file_count,
)
from mclaw.shared.organize.preview_cards import BUCKET_CARD_DISPLAY_LIMIT
from mclaw.shared.organize.bucket.result import (
    ClusterResult,
    DEFAULT_SET_THRESHOLD,
    bucket_assignment_count,
    distinct_excluding_unknown,
    group_by_bucketer,
)
from mclaw.shared.organize.bucket.time_bucket import TIME_BUCKET_NAMES


def cluster_one(
    files: List[File],
    bucket_name: str,
    *,
    threshold: Optional[int] = None,
) -> ClusterResult:
    """通用单维度聚类。

    Args:
        files: 待聚类的 File 列表
        bucket_name: 桶名（必须已在 ``BUCKET_REGISTRY`` 注册）
        threshold: distinct 值上限阈值；给定且 distinct > threshold 时
            ``ClusterResult.too_many=True`` 并附 ``reason`` 文案。
            单值桶通常传 ``None``（不判断阈值）。

    Returns:
        ``ClusterResult``，``field`` 为桶名
    """
    buckets = group_by_bucketer(files, bucket_name)
    distinct = distinct_excluding_unknown(buckets)
    too_many = threshold is not None and distinct > threshold
    reason = ''
    if too_many:
        reason = (
            f'该维度（{bucket_name}）共 {distinct} 个不同值，超过阈值 {threshold}，'
            f'不建议以此维度整理；请改用时间或地点。'
        )
    bucketer_cls = BUCKET_REGISTRY.get_class(bucket_name)
    assignment_count = bucket_assignment_count(buckets)
    return ClusterResult(
        field=bucket_name,
        granularity=bucket_name if bucket_name in TIME_BUCKET_NAMES else '',
        buckets=buckets,
        distinct_count=distinct,
        too_many=too_many,
        reason=reason,
        is_multi_value=bucketer_cls.is_multi_value,
        unique_file_count=len(files),
        bucket_assignment_count=assignment_count,
    )


def profile_all_dimensions(
    files: List[File],
    *,
    time_granularity: str = 'month',
    set_threshold: int = DEFAULT_SET_THRESHOLD,
) -> Dict[str, ClusterResult]:
    """扫描全部分类的默认桶，返回 ``{分类名: ClusterResult}``。

    数据驱动：迭代 ``BUCKET_REGISTRY.categories()``，每个分类取其默认桶
    （``BucketCategoryInfo.default``）做聚类；分类无默认桶时跳过。

    默认桶为多值时应用 ``set_threshold`` 做 too_many 判断；
    默认桶为单值时 ``threshold=None``。

    新增分类（如外部注册的 ``device``）声明 ``is_default_in_bucket_category=True``
    后会**自动纳入**画像，无需改本函数。
    """
    results: Dict[str, ClusterResult] = {}
    for cat_name, cat in BUCKET_REGISTRY.categories().items():
        if cat.default is None:
            continue
        default_cls = BUCKET_REGISTRY.get_class(cat.default)
        threshold = set_threshold if default_cls.is_multi_value else None
        results[cat_name] = cluster_one(files, cat.default, threshold=threshold)
    return results


def _non_empty_bucket_map(bucket_map: Dict[str, List[Any]]) -> Dict[str, List[Any]]:
    return {name: files for name, files in bucket_map.items() if files}


def _bucket_display_summary(
    bucket_map: Dict[str, List[Any]],
    *,
    too_many: bool = False,
    full_key: str = '类别数量明细',
    sample_key_template: str = '类别示例（前{limit}个）',
    display_limit: Optional[int] = BUCKET_CARD_DISPLAY_LIMIT,
) -> tuple[str, List[str]]:
    """非空桶统计行（顺序/上限与 stdout 分桶卡对齐）。

    ``display_limit``：类别明细的展示上限，默认 ``BUCKET_CARD_DISPLAY_LIMIT``。
    传 ``None`` 表示**不截断**——始终以 ``full_key`` 输出全部类别（含 index），
    不切换到「类别示例（前N个）」；``too_many`` 也不影响明细完整性
    （是否超阈值仍由独立的 ``类别过多`` 字段表达）。
    """
    non_empty = _non_empty_bucket_map(bucket_map)
    sorted_names = sort_bucket_keys(non_empty)
    summary_lines = [
        f'{index}. {name}: 数量{len(non_empty[name])}'
        for index, name in enumerate(sorted_names, start=1)
    ]
    if display_limit is None:
        return full_key, summary_lines
    if len(sorted_names) <= display_limit and not too_many:
        return full_key, summary_lines
    limit = display_limit
    return sample_key_template.format(limit=limit), summary_lines[:limit]


def format_cluster_report(
    result: ClusterResult,
    *,
    display_limit: Optional[int] = BUCKET_CARD_DISPLAY_LIMIT,
) -> str:
    """把 ``ClusterResult`` 格式化为 ``cluster_profile`` JSON 行。

    输出单行 JSON（``ensure_ascii=False`` 保留中文），字段：

    - ``record``: 固定 ``'cluster_profile'``
    - ``聚类字段名``: 桶名（如 ``month`` / ``city`` / ``thingLabelList``）
    - ``时间粒度``: 仅时间桶（``day`` / ``month`` / ``year``）时出现
    - ``文件总数``: 参与聚类的唯一文件数（与搜图去重后条数一致）
    - ``分桶计数合计``: 仅多值桶且合计大于 ``文件总数`` 时出现
    - ``类别个数``: distinct 桶数（不含 UNKNOWN）
    - ``类别数量明细``: ``["1. 桶名: 数量N", ...]``（按桶名排序）
    - ``类别过多``: 是否超阈值
    - ``异常类别文件数目``: UNKNOWN 桶文件数
    - ``异常msg``: 阈值超限原因

    Args:
        result: ``ClusterResult`` 实例
        display_limit: 类别明细展示上限，默认 ``BUCKET_CARD_DISPLAY_LIMIT``。
            传 ``None`` 输出全部类别（含 index，不截断）。
    """
    bucket_summary_key, bucket_summary = _bucket_display_summary(
        result.buckets,
        too_many=result.too_many,
        display_limit=display_limit,
    )
    payload: dict[str, Any] = {
        'record': 'cluster_profile',
        '聚类字段名': result.field,
        '文件总数': result.unique_file_count,
        '类别个数': result.distinct_count,
        bucket_summary_key: bucket_summary,
        '类别过多': result.too_many,
        '异常类别文件数目': unknown_bucket_file_count(result.buckets),
        '异常msg': result.reason,
    }
    if result.granularity:
        payload['时间粒度'] = result.granularity
    if (
        result.is_multi_value
        and result.bucket_assignment_count > result.unique_file_count
    ):
        payload['分桶计数合计'] = result.bucket_assignment_count
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------
# 多维度可视化（formatter）
#
# 聚类（cross / hierarchical）逻辑由调用方在模板或上层脚本完成，
# 本节只提供把聚类结果转为 JSON 行的格式化器。
# ---------------------------------------------------------------------


def format_cross_report(
    buckets_spec: List[str],
    bucket_map: Dict[str, List[File]],
) -> str:
    """交叉聚类（平铺）→ ``cluster_profile`` JSON 行。

    输出字段：
    - ``record``: ``'cluster_profile'``
    - ``mode``: ``'cross'``
    - ``维度``: ``'a_b'`` 连接
    - ``类别个数``: distinct 组合桶数
    - ``类别数量明细`` / ``类别示例（前N个）``: ``["1. 桶名: 数量N", ...]``（非空桶、``sort_bucket_keys``）

    Args:
        buckets_spec: 维度桶名列表（用于展示），如 ``['month', 'city']``
        bucket_map: ``cluster_cross`` 的返回值，``{组合桶名: [File]}``
    """
    non_empty = _non_empty_bucket_map(bucket_map)
    bucket_summary_key, bucket_summary = _bucket_display_summary(bucket_map)
    payload: dict[str, Any] = {
        'record': 'cluster_profile',
        'mode': 'cross',
        '维度': '_'.join(buckets_spec),
        '类别个数': len(non_empty),
        bucket_summary_key: bucket_summary,
    }
    return json.dumps(payload, ensure_ascii=False)


def _tree_to_summary(node: Any) -> Any:
    """递归把层级嵌套树转为 count 树。

    叶子层（``[File]``）→ 整数 count；
    中间层（``dict``）→ ``{桶名: <子树>}``。
    """
    if isinstance(node, list):
        return len(node)
    return {k: _tree_to_summary(v) for k, v in node.items()}


def _flatten_tree_bucket_map(tree: Any) -> Dict[str, List[Any]]:
    """层级树 → 叶子 bucket 映射，bucket 名使用完整路径。"""
    bucket_map: Dict[str, List[Any]] = {}

    def _walk(node: Any, path: List[str]) -> None:
        if isinstance(node, list):
            if not node:
                return
            bucket_name = ' / '.join(path) if path else 'UNKNOWN'
            bucket_map[bucket_name] = node
            return
        for key, child in node.items():
            _walk(child, [*path, str(key)])

    _walk(tree, [])
    return bucket_map


def format_hierarchical_report(
    buckets_spec: List[str],
    tree: Any,
) -> str:
    """层级聚类（嵌套）→ ``cluster_hierarchical_profile`` JSON 行。

    用嵌套 dict 直接表达层级关系，每层 key 是桶名，value 是子树；
    叶子节点为该桶的文件数（整数）。

    输出示例（``buckets=['location','month']``）::

        {"record":"cluster_hierarchical_profile",
         "层级维度":["location","month"],
         "层级数":2,
         "层级结构":{"上海市":{"2026-01":1,"2026-02":1},
                    "北京市":{"2026-04":1}},
         "类别数量明细":["1. 北京市 / 2026-04: 数量1",
                      "2. 上海市 / 2026-01: 数量1",
                      "3. 上海市 / 2026-02: 数量1"]}

    Args:
        buckets_spec: 层级维度桶名列表（按层级顺序），如 ``['year', 'city']``
        tree: ``cluster_hierarchical`` 的返回值，嵌套 dict
    """
    bucket_summary_key, bucket_summary = _bucket_display_summary(
        _flatten_tree_bucket_map(tree),
    )
    payload: dict[str, Any] = {
        'record': 'cluster_hierarchical_profile',
        'mode': 'hierarchical',
        '层级维度': buckets_spec,
        '层级数': len(buckets_spec),
        '层级结构': _tree_to_summary(tree),
        bucket_summary_key: bucket_summary,
    }
    return json.dumps(payload, ensure_ascii=False)
