#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""相似图去重 + 回忆故事去重前过滤入口（facade）。

薄入口，委托 ``selector.ImageDeduplicator`` / ``selector.MemoryPhotoFilter``：
  - ``deduplicate_files``：相似图去重（File 级，fileId 级原子能力见 ``ImageDeduplicator.deduplicate``）
  - ``filter_files_for_memory_plan`` / ``ensure_sufficient_memory_photos``：
    去重前过滤（事物标签黑名单 + 拍摄时间）与入选数校验
  - ``refine_for_memory``：回忆故事完整精选编排（filter→collapse_exact→dedup→ensure→top-N，
    逐桶），供整理到回忆故事（task_type=3）的整理流程复用

与 ``selector/image_deduplicator.py``（``ImageDeduplicator`` 原语类）区分：本模块是
organize 层的**入口 facade**，selector 子模块是以类命名的**原语**。

**不发 HTTP、不持鉴权/host**——dispatcher 由调用方构造并注入
（``ApiDispatcher(host=HOST, auth_fn=get_auth_header)``），见 ``mclaw.shared.image_tools``）。
``refine_for_memory`` 同样不自行取 dispatcher：调用方传入，避免在 facade 层引入 host/鉴权。
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from mclaw.api import ApiDispatcher
from mclaw.api.search_fusion import File
from mclaw.shared.organize.select_photo import select_photos
from mclaw.shared.organize.selector.image_deduplicator import (
    DEFAULT_DEDUP_MAX_WORKERS,
    MAX_FILE_ID_LIST_SIZE,
    ImageDeduplicator,
)
from mclaw.shared.organize.selector.memory_photo_filter import (
    INSUFFICIENT_MEMORY_PHOTOS_MESSAGE,
    MEMORY_EXCLUDED_THING_LABELS,
    MEMORY_INVALID_TAKEN_AT_DATE,
    MEMORY_PLAN_MIN_FILE_COUNT,
    MemoryPhotoFilter,
)
from mclaw.shared.organize.selector.quality_selector import QualitySelector
from mclaw.utils.logger import openclaw_logger, status_log


__all__ = [
    'collapse_exact_duplicates',
    'deduplicate_files',
    'filter_files_for_memory_plan',
    'ensure_sufficient_memory_photos',
    'refine_for_memory',
    'MemoryRefineStats',
    'ImageDeduplicator',
    'MemoryPhotoFilter',
    'QualitySelector',
    'MAX_FILE_ID_LIST_SIZE',
    'DEFAULT_DEDUP_MAX_WORKERS',
    'MEMORY_EXCLUDED_THING_LABELS',
    'MEMORY_INVALID_TAKEN_AT_DATE',
    'MEMORY_PLAN_MIN_FILE_COUNT',
    'INSUFFICIENT_MEMORY_PHOTOS_MESSAGE',
    'MEMORY_TOP_DEFAULT',
    'REFINE_MEMORY_MAX_WORKERS',
]


def _hash_key(file_: File) -> Optional[Tuple[str, str]]:
    """``(contentHashAlgorithm, contentHash)`` 元组；缺 hash 返回 ``None``。"""
    h = str(getattr(file_, 'content_hash', '') or '').strip()
    if not h:
        return None
    algo = str(getattr(file_, 'content_hash_algorithm', '') or '').strip().lower()
    return (algo, h)


def _img_quality(file_: File) -> float:
    """安全取 ``aiAnalysisInfo.imageQuality.imgQuality``，缺失 → 0.0。"""
    ai = getattr(file_, 'ai_analysis_info', None)
    iq = getattr(ai, 'image_quality', None) if ai is not None else None
    return float(getattr(iq, 'img_quality', 0.0) or 0.0) if iq is not None else 0.0


def collapse_exact_duplicates(files: List[File]) -> Tuple[List[File], int]:
    """本地**精确**去重：按 ``(contentHashAlgorithm, contentHash)`` 分组，每组仅留
    ``imgQuality`` 最高的一张（同分 fileId 升序，与相似图接口 tie-break 一致）；
    无 hash / 无 fileId 的文件原样透传。返回 ``(代表集[保持原序], 精确重复移除数)``。

    **零网络**：完全相同的图（重复上传 / 多端备份）在此免费摘除，无需送相似图接口，
    是 ``deduplicate_files``（网络相似图去重）的前置互补段。内存友好：只经手
    fileId/hash 字符串与 File 引用，无深拷贝。
    """
    winner_by_key: Dict[Tuple[str, str], Tuple[float, str]] = {}  # key -> (quality, fileId)
    for f in files:
        fid = str(getattr(f, 'file_id', '') or '').strip()
        if not fid:
            continue
        key = _hash_key(f)
        if key is None:
            continue
        q = _img_quality(f)
        cur = winner_by_key.get(key)
        if cur is None or q > cur[0] or (q == cur[0] and fid < cur[1]):
            winner_by_key[key] = (q, fid)

    reps: List[File] = []
    removed = 0
    for f in files:
        fid = str(getattr(f, 'file_id', '') or '').strip()
        key = _hash_key(f) if fid else None
        if key is None:
            reps.append(f)                          # 无 hash / 无 fileId：透传
        elif fid == winner_by_key[key][1]:
            reps.append(f)                          # 该 hash 组代表
        else:
            removed += 1                            # 完全相同的重复 → 本地消除
    return reps, removed


def deduplicate_files(
    api_client: ApiDispatcher,
    files: List[File],
    *,
    max_workers: Optional[int] = DEFAULT_DEDUP_MAX_WORKERS,
) -> Tuple[List[File], int]:
    """相似图去重并映射回 ``File`` 列表。返回 ``(去重后 files, 移除张数)``。

    ``max_workers``：分批调用的并行上限（默认 4），语义同 ``ImageDeduplicator.deduplicate``。
    """
    return ImageDeduplicator(api_client, max_workers=max_workers).deduplicate_files(files)


def filter_files_for_memory_plan(files: List[File]) -> Tuple[List[File], Dict[str, int]]:
    """回忆故事去重前过滤（事物标签 → 拍摄时间）。返回 ``(保留 files, 统计)``。"""
    return MemoryPhotoFilter().filter(files)


def ensure_sufficient_memory_photos(files: List[File]) -> None:
    """过滤与去重后入选数须 ≥ ``MEMORY_PLAN_MIN_FILE_COUNT``，否则抛 ``ValueError``。"""
    MemoryPhotoFilter().ensure_sufficient(files)


#: 回忆故事每桶精选默认上限（与旧 memory cap 对齐）。
MEMORY_TOP_DEFAULT: int = 50

#: ``refine_for_memory`` 外层逐桶并行上限（与内层 ``DEFAULT_DEDUP_MAX_WORKERS`` 解耦、单独可调）。
#: 多桶时步骤 1-3 各桶并行；外层并行时各桶内相似图去重降 ``max_workers=1`` 串行，
#: 避免外 N × 内 4 瞬时并发打爆接口。单桶或本值 ≤1 时退化为串行。
REFINE_MEMORY_MAX_WORKERS: int = 4


@dataclass
class MemoryRefineStats:
    """回忆故事逐桶精选的聚合统计（供整理 plan 回执透出）。

    聚合**所有桶**的变换计数：每桶独立 filter/collapse_exact/deduplicate/top-N，
    本结构把各桶移除数相加。
    """

    label_filtered: int = 0       # 事物标签黑名单移除
    taken_at_filtered: int = 0    # 拍摄时间无效移除
    dedup_exact_removed: int = 0  # 精确 contentHash 去重移除（本地零网络）
    dedup_similar_removed: int = 0  # 相似图 API 去重移除
    bucket_count: int = 0         # 入选桶数（精选后仍有文件的桶）
    picked: int = 0               # top-N 精选后保留总数

    @property
    def removed_total(self) -> int:
        """前置过滤 + 去重合计移除数（不含 top-N 截断）。"""
        return (
            self.label_filtered
            + self.taken_at_filtered
            + self.dedup_exact_removed
            + self.dedup_similar_removed
        )


def _refine_one_memory_bucket(
    bucket_files: List[File],
    dispatcher: ApiDispatcher,
    *,
    inner_dedup_workers: int,
) -> Tuple[List[File], int, int, int, int]:
    """单桶 filter → collapse_exact → deduplicate（桶间独立，不展平）。

    返回 ``(存活 files, label_filtered, taken_at_filtered, exact_removed, similar_removed)``。
    桶内顺序与 ``refine_for_memory`` 逐桶段一致：空桶/门后空/精确去重后空均返回空存活 +
    截止该步的计数（后续步不再执行）。``inner_dedup_workers`` 收敛嵌套并行：外层按桶并行时
    传 1（桶内相似图去重串行），串行兜底传 ``DEFAULT_DEDUP_MAX_WORKERS``。异常不额外吞——
    ``deduplicate_files`` 接口失败已自行降级保留入参，其余异常向上抛（外层经 future 上抛）。
    """
    if not bucket_files:
        return [], 0, 0, 0, 0
    kept, fstats = filter_files_for_memory_plan(bucket_files)
    label_filtered = int(fstats.get('thing_label_filtered_removed', 0) or 0)
    taken_at_filtered = int(fstats.get('taken_at_filtered_removed', 0) or 0)
    if not kept:
        return [], label_filtered, taken_at_filtered, 0, 0
    kept, exact_removed = collapse_exact_duplicates(kept)
    if not kept:
        return [], label_filtered, taken_at_filtered, exact_removed, 0
    kept, similar_removed = deduplicate_files(
        dispatcher, kept, max_workers=inner_dedup_workers
    )
    return kept, label_filtered, taken_at_filtered, exact_removed, similar_removed


def _refine_memory_via_select_photo(
    buckets: Dict[str, List[File]],
    dispatcher: ApiDispatcher,
    *,
    top_n: int,
) -> Tuple[Dict[str, List[File]], MemoryRefineStats]:
    """回忆故事 AI 选图路径：逐桶 filter→collapse_exact → 整批 ensure → 逐桶 AI 选图。

    与 legacy 的差异仅两步：「相似图 API 去重」与「imgQuality top-N」换成
    ``select_photos``（count=每桶上限，不传 query/threshold）。门/精确去重/
    ensure 辖域、空桶剔除、统计口径与 legacy 一致；``dedup_similar_removed``
    恒 0（选图接口不回移除数）。

    Raises:
        ValueError: 整批入选数不足（``ensure_sufficient``）或精选后无可用照片——
            与 legacy 同口径，**不触发**调用方的异常回退（空结果是真实结果）。
    """
    stats = MemoryRefineStats()
    effective_top = int(top_n) if top_n and top_n > 0 else MEMORY_TOP_DEFAULT

    deduped_buckets: Dict[str, List[File]] = {}
    all_survivors: List[File] = []
    for bucket_name, bucket_files in buckets.items():
        if not bucket_files:
            continue
        kept, fstats = filter_files_for_memory_plan(bucket_files)
        stats.label_filtered += int(fstats.get('thing_label_filtered_removed', 0) or 0)
        stats.taken_at_filtered += int(fstats.get('taken_at_filtered_removed', 0) or 0)
        if not kept:
            continue
        kept, exact_removed = collapse_exact_duplicates(kept)
        stats.dedup_exact_removed += exact_removed
        if not kept:
            continue
        deduped_buckets[bucket_name] = kept
        all_survivors.extend(kept)

    ensure_sufficient_memory_photos(all_survivors)

    # 逐桶 AI 选图（多桶并行，上限与 legacy 步骤 1-3 一致）
    if len(deduped_buckets) > 1 and REFINE_MEMORY_MAX_WORKERS > 1:
        with ThreadPoolExecutor(max_workers=REFINE_MEMORY_MAX_WORKERS) as pool:
            futures = {
                name: pool.submit(select_photos, dispatcher, kept, count=effective_top)
                for name, kept in deduped_buckets.items()
            }
            picked_by_bucket = {name: fut.result() for name, fut in futures.items()}
    else:
        picked_by_bucket = {
            name: select_photos(dispatcher, kept, count=effective_top)
            for name, kept in deduped_buckets.items()
        }

    refined: Dict[str, List[File]] = {}
    for bucket_name, picked in picked_by_bucket.items():
        if not picked:
            continue
        refined[bucket_name] = picked
        stats.picked += len(picked)
        stats.bucket_count += 1

    if not refined:
        raise ValueError('回忆故事精选后无可用照片；请调整搜索条件或聚类维度')
    return refined, stats


def refine_for_memory(
    buckets: Dict[str, List[File]],
    dispatcher: ApiDispatcher,
    *,
    top_n: int = MEMORY_TOP_DEFAULT,
    use_select_photo: bool = False,
) -> Tuple[Dict[str, List[File]], MemoryRefineStats]:
    """回忆故事完整精选编排（逐桶 filter/collapse_exact/dedup → 整批 ensure → 逐桶 top-N）。

    把「整理到回忆故事（task_type=3）」的质量门收口为一处，供整理 plan 复用。
    顺序固定（遵循 ``MemoryPhotoFilter.ensure_sufficient`` 契约「过滤与去重后入选数」）：

    1. 逐桶 ``filter_files_for_memory_plan`` —— 事物标签黑名单（证件/截图/文档…）+ 拍摄时间校验；
    2. 逐桶 ``collapse_exact_duplicates`` —— 本地 contentHash 精确去重（零网络，是相似图去重的
       前置互补段，完全相同的图在此免费摘除，不送相似图接口）；
    3. 逐桶 ``deduplicate_files`` —— 相似图 API 去重（dispatcher 由调用方注入）；
    4. **整批** ``ensure_sufficient_memory_photos`` —— 去重后全部入选数 ≥ ``MEMORY_PLAN_MIN_FILE_COUNT``，
       否则抛 ``ValueError``（由调用方转译为技能 ServiceError）。整批而非逐桶：回忆故事整体
       需有足够素材，稀疏桶（1 张）仍可成故事，只在「全体都不够」时阻断；
    5. 逐桶 ``QualitySelector.select_global_top_n`` —— 桶内 imgQuality top-N（无质量分按拍摄时间）。

    **步骤 1-3 逐桶并行**（上限 ``REFINE_MEMORY_MAX_WORKERS``，单桶/上限≤1 退化为串行；
    结果按桶序归并、与串行一致），**步骤 5 top-N 串行**（纯本地）。各桶独立保留各自代表图
    （不展平整批）：展平会让 A 桶的相似图在 B 桶胜出、B 桶副本被整体移除，桶之间失去独立
    代表性。整批 ensure 是唯一跨桶步骤（只统计总数，不改归属）。

    Args:
        buckets: 聚类后的桶 → 文件列表（``run_cluster`` 的 flat 产物，或拍平后的 tree）。
        dispatcher: 调用方注入的 ``ApiDispatcher``（相似图去重经它触网，不在 facade 层自取）。
        top_n: 每桶精选上限，默认 ``MEMORY_TOP_DEFAULT=50``。
        use_select_photo: True 时「相似图 API 去重 + imgQuality top-N」两步换成
            ``select_photos`` AI 选图（``_refine_memory_via_select_photo``）；提交/轮询
            异常打 traceback 日志并回退本 legacy 全流程。``ValueError``（素材不足/
            精选后为空）不回退——空结果是真实结果，按既有口径上抛。

    Returns:
        ``(精炼后 buckets, 统计)``：只保留精选后仍有文件的桶；桶内为 top-N 代表图。

    Raises:
        ValueError: 去重后整批入选数不足（``ensure_sufficient`` 抛出）——调用方应转译为
            技能 ServiceError，提示调整搜索条件或聚类维度。
    """
    if use_select_photo:
        try:
            return _refine_memory_via_select_photo(buckets, dispatcher, top_n=top_n)
        except ValueError:
            raise
        except Exception:
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[WARN] AI 选图精选失败，已回退相似图去重+质量评分。exc={flat_exc}',
                logger=openclaw_logger,
                info_dict={'api': 'refine_for_memory'},
                server_type='SYNC',
                stdout=True,
            )

    selector = QualitySelector()
    stats = MemoryRefineStats()

    # 1-3) 逐桶 filter → collapse_exact → deduplicate（不展平，桶间独立；多桶并行）
    ordered = [(name, files) for name, files in buckets.items() if files]
    # 多桶时步骤 1-3 各桶并行（上限 REFINE_MEMORY_MAX_WORKERS），按桶序提交+收集，
    # 结果与串行一致；单桶/上限≤1 退化为串行。外层并行时桶内相似图去重降 max_workers=1
    # 收敛嵌套（外 N × 内 4 瞬时并发打爆接口）；串行维持内层默认分批并行。
    parallel = len(ordered) > 1 and REFINE_MEMORY_MAX_WORKERS > 1
    inner_dedup_workers = 1 if parallel else DEFAULT_DEDUP_MAX_WORKERS
    if parallel:
        with ThreadPoolExecutor(max_workers=REFINE_MEMORY_MAX_WORKERS) as pool:
            futures = [
                pool.submit(
                    _refine_one_memory_bucket, files, dispatcher,
                    inner_dedup_workers=inner_dedup_workers,
                )
                for _name, files in ordered
            ]
            results = [fut.result() for fut in futures]
    else:
        results = [
            _refine_one_memory_bucket(
                files, dispatcher, inner_dedup_workers=inner_dedup_workers
            )
            for _name, files in ordered
        ]

    deduped_buckets: Dict[str, List[File]] = {}
    all_survivors: List[File] = []
    for (bucket_name, _files), (kept, lf, tf, er, sr) in zip(ordered, results):
        stats.label_filtered += lf
        stats.taken_at_filtered += tf
        stats.dedup_exact_removed += er
        stats.dedup_similar_removed += sr
        if kept:
            deduped_buckets[bucket_name] = kept
            all_survivors.extend(kept)

    # 4) 整批入选数校验（去重后、top-N 前）
    ensure_sufficient_memory_photos(all_survivors)

    # 5) 逐桶 top-N
    refined: Dict[str, List[File]] = {}
    effective_top = int(top_n) if top_n and top_n > 0 else MEMORY_TOP_DEFAULT
    for bucket_name, kept in deduped_buckets.items():
        picked = selector.select_global_top_n(kept, effective_top)
        if not picked:
            continue
        refined[bucket_name] = picked
        stats.picked += len(picked)
        stats.bucket_count += 1

    if not refined:
        raise ValueError('回忆故事精选后无可用照片；请调整搜索条件或聚类维度')
    return refined, stats
