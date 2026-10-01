#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片质量筛选模块。

本模块提供通用图片质量筛选能力（基于 ``mclaw.api.search_fusion._models.File``）：

    - ``select_top_n_per_bucket``：桶 × N 采样
      桶可以是**任意维度**：时间（day/week/month/year）、城市、人物、关系、事物标签、
      地标名人…… 不限于时间，时间只是最常见示例
    - ``select_global_top_n``：全集按 img_quality 降序取前 N
    - 用户搜图后想挑选、且未指定维度时 → 用 ``select_global_top_n``

设计：
    - 不修改 ``File`` 实例（Pydantic v2 模型默认可变，但本模块只读不写）
    - img_quality 缺失视为 0.0
    - bucket_fn 返回 str 或 list[str]（多值字段可同时进多个桶；最终结果按 file_id 去重）

与 ``cm_cloud_organize/scripts/quality_selector.py`` 的差异：
    - ``File`` 来源：本模块用 ``mclaw.api.search_fusion._models.File``
      （Pydantic v2，snake_case 字段 + camelCase alias），原模块用本地
      ``file_model.File``（dataclass，camelCase 字段）。
    - 默认 ``n``：原模块从 ``manage_bootstrap.load_organize_settings()`` 读
      ``QUALITY_GLOBAL_TOP_N``；本模块**去除默认值**，调用方必传 ``n``。
    - ``build_bucket_fn`` re-export：原模块 ``# noqa: F401`` 转手再导出一次；
      本模块删除该 re-export，调用方需要时直接从 ``mclaw.shared.organize.bucket`` 取。

权威来源：``File.ai_analysis_info.image_quality.img_quality`` 见
``dev/docs/api/cm_cloud_search_fusion.md`` §图片质量 ImageQuality。
"""

from __future__ import annotations

from typing import Callable, List, Union

from mclaw.api.search_fusion import File


# ----------------------------------------------------------------------
# img_quality 取值
# ----------------------------------------------------------------------

def get_img_quality(file_: File) -> float:
    """安全取 ``img_quality``；缺失返回 0.0。"""
    ai = file_.ai_analysis_info
    if ai is None or ai.image_quality is None:
        return 0.0
    return float(ai.image_quality.img_quality or 0.0)


# ----------------------------------------------------------------------
# QualitySelector
# ----------------------------------------------------------------------

class QualitySelector:
    """通用图片质量筛选器。

    通用筛选方法（任何场景可用）：
    - ``select_top_n_per_bucket``：桶 × N（如「每月 2 张」→ 月桶内 img_quality top-2）
    - ``select_global_top_n``：全集 img_quality 降序取前 N
    """

    def select_top_n_per_bucket(
        self,
        files: List[File],
        bucket_fn: Callable[[File], Union[str, List[str]]],
        n: int,
    ) -> List[File]:
        """桶内按 img_quality 降序取前 N；返回扁平化 list（按桶名升序，UNKNOWN 在末尾）。

        ``bucket_fn`` 返回值可以是：
        - ``str``：单桶（如时间粒度、city）
        - ``list[str]``：多桶（如多值 set 字段 thing_label_list）；
          一个 file 可同时进多个桶；最终结果按 file_id 去重

        桶内同分按 file_id 升序稳定。
        """
        if n < 1:
            raise ValueError(f'n 须为正整数，收到 {n}')
        buckets: dict[str, List[File]] = {}
        for f in files:
            keys = bucket_fn(f)
            if isinstance(keys, str):
                keys = [keys]
            for key in keys:
                buckets.setdefault(key, []).append(f)

        ordered_keys = sorted(k for k in buckets if k != 'UNKNOWN')
        if 'UNKNOWN' in buckets:
            ordered_keys.append('UNKNOWN')

        seen: set[str] = set()
        result: List[File] = []
        for key in ordered_keys:
            picked = sorted(
                buckets[key],
                key=lambda f: (-get_img_quality(f), f.file_id),
            )[:n]
            for f in picked:
                if f.file_id and f.file_id not in seen:
                    seen.add(f.file_id)
                    result.append(f)
        return result

    def select_global_top_n(self, files: List[File], n: int) -> List[File]:
        """全集 img_quality 降序取前 N。"""
        if n < 1:
            raise ValueError(f'n 须为正整数，收到 {n}')
        return sorted(files, key=lambda f: (-get_img_quality(f), f.file_id))[:n]
