#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组内去重 + 精选变换（organize plan 内嵌，不落 subset jsonl）。

对分桶后的**每个桶**做：
  - 去重（若 ``dedup`` 开）：精确 contentHash（零网络）→ 相似图 API（照片专属）；
  - 精选（若 ``pick > 0``）：桶内图片按 imgQuality 取前 N（无质量分按拍摄时间）。

仅 ``category=='image'`` 参与去重/精选（照片专属）；非图片行**透传**（戒律 17）。
变换在内存完成，结果直接进 plan.jsonl 的 rows——被剔掉的文件不进 rows。

跨 skill 复用：drive（个人云目录）与 album/memory（相册 / 回忆故事）的
逐桶去重/精选共用本变换。回忆故事（memory）的完整质量门（filter→collapse_exact→
dedup→ensure→top-N）走 ``dedup.refine_for_memory``；本模块是其 drive 路径下的逐桶变体，
驱动文件操作不触网外的去重接口（dispatcher 由 ``get_cloud_dispatcher`` 取）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from mclaw.api.search_fusion import File
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.organize.dedup import collapse_exact_duplicates, deduplicate_files
from mclaw.shared.organize.selector import (
    MemoryPhotoFilter,
    QualitySelector,
)


def _is_image(f: File) -> bool:
    return str(getattr(f, 'category', '') or '').lower() == 'image'


def _file_id(f: File) -> str:
    return str(getattr(f, 'file_id', '') or '').strip()


@dataclass
class TransformStats:
    """单桶变换统计（聚合后进 plan 回执）。"""
    dedup_exact_removed: int = 0      # 精确去重移除数
    dedup_similar_removed: int = 0    # 相似图去重移除数
    picked: int = 0                  # 精选保留数（pick>0 时有意义）
    label_filtered: int = 0          # 前置过滤移除（证件/截图标签）
    taken_at_filtered: int = 0       # 前置过滤移除（拍摄时间）


def transform_leaf_files(
    files: List[File],
    *,
    pick: int,
    dedup: bool,
) -> Tuple[List[File], TransformStats]:
    """对一个桶的 files 做去重 + 精选，返回 ``(保留 files, 统计)``。

    非图片行透传；仅图片行参与去重/精选，最终按原顺序拼回（保留集过滤）。
    ``pick<=0`` 跳过精选；``dedup=False`` 跳过去重（``pick>0`` 时调用方应已强制 dedup=True）。
    """
    stats = TransformStats()
    images = [f for f in files if _is_image(f)]
    others = [f for f in files if not _is_image(f)]

    if not images:
        # 无图片：无可去重/精选对象，原样返回（计数 0）
        return list(files), stats

    kept_imgs: List[File] = images

    # 1) 前置过滤：证件/截图/文档标签 + takenAt 校验（纯本地，统计进回执）
    kept_imgs, fstats = MemoryPhotoFilter().filter(kept_imgs)
    stats.label_filtered = int(fstats.get('thing_label_filtered_removed', 0) or 0)
    stats.taken_at_filtered = int(fstats.get('taken_at_filtered_removed', 0) or 0)

    # 2) 去重：精确 contentHash（零网络）→ 相似图 API（照片专属，接口失败降级保留入参）
    if dedup and kept_imgs:
        deduped_imgs, exact_removed = collapse_exact_duplicates(kept_imgs)
        stats.dedup_exact_removed = exact_removed
        deduped_imgs2, similar_removed = deduplicate_files(
            get_cloud_dispatcher(), deduped_imgs
        )
        stats.dedup_similar_removed = similar_removed
        kept_imgs = deduped_imgs2

    # 3) 精选：桶内图片按 imgQuality 取前 N（无质量分按拍摄时间）
    if pick > 0 and kept_imgs:
        kept_imgs = QualitySelector().select_global_top_n(kept_imgs, pick)
        stats.picked = len(kept_imgs)

    # 按保留 fileId 集过滤回原文件顺序（非图片透传 + 存活图片）
    survivors = {_file_id(f) for f in kept_imgs}
    result = [
        f for f in files
        if not _is_image(f) or _file_id(f) in survivors
    ]
    return result, stats


__all__ = ['TransformStats', 'transform_leaf_files']
