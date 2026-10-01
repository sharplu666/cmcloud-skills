#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚类产物上的 img_quality top 裁剪（Step 2 预览与 Step 4 规划共用）。"""

from __future__ import annotations

from typing import Any, Dict, List

from mclaw.api.search_fusion import File
from mclaw.shared.organize.selector.quality_selector import QualitySelector


def apply_select_to_flat(
    flat: Dict[str, List[File]],
    top: int,
) -> Dict[str, List[File]]:
    """对平铺桶（single / cross）逐桶按 img_quality 降序取前 N。"""
    if int(top or 0) <= 0:
        return flat
    selector = QualitySelector()
    return {key: selector.select_global_top_n(files, top) for key, files in flat.items()}


def apply_select_to_tree(tree: Dict[str, Any], top: int) -> Dict[str, Any]:
    """对层级树（hierarchical）逐叶子桶取前 N。"""
    if int(top or 0) <= 0:
        return tree
    selector = QualitySelector()

    def _prune(node: Any) -> Any:
        if isinstance(node, list):
            return selector.select_global_top_n(node, top)
        return {key: _prune(child) for key, child in node.items()}

    return _prune(tree)
