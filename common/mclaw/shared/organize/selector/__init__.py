#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.shared.organize.selector —— 图片挑选（selector）共享业务编排层。

  - ``quality_selector`` / ``apply_select``：桶 × N / 全集 top-N 图片质量挑选
    + 聚类产物 top 裁剪（``apply_select_to_flat`` / ``apply_select_to_tree``）
  - ``image_deduplicator``：相似图去重原子能力（fileId→fileId / File→File）；
    HTTP 经调用方注入的 dispatcher 完成，不持 host/鉴权
  - ``memory_photo_filter``：回忆故事去重前过滤（事物标签黑名单 + 拍摄时间）
"""

from mclaw.shared.organize.selector.apply_select import (  # noqa: F401
    apply_select_to_flat,
    apply_select_to_tree,
)
from mclaw.shared.organize.selector.image_deduplicator import (  # noqa: F401
    DEFAULT_DEDUP_MAX_WORKERS,
    MAX_FILE_ID_LIST_SIZE,
    ImageDeduplicator,
    filter_files_by_ids,
)
from mclaw.shared.organize.selector.memory_photo_filter import (  # noqa: F401
    INSUFFICIENT_MEMORY_PHOTOS_MESSAGE,
    MEMORY_EXCLUDED_THING_LABELS,
    MEMORY_INVALID_TAKEN_AT_DATE,
    MEMORY_PLAN_MIN_FILE_COUNT,
    MemoryPhotoFilter,
)
from mclaw.shared.organize.selector.quality_selector import (  # noqa: F401
    QualitySelector,
    get_img_quality,
)

__all__ = [
    'QualitySelector',
    'get_img_quality',
    'apply_select_to_flat',
    'apply_select_to_tree',
    'ImageDeduplicator',
    'filter_files_by_ids',
    'MAX_FILE_ID_LIST_SIZE',
    'DEFAULT_DEDUP_MAX_WORKERS',
    'MemoryPhotoFilter',
    'MEMORY_EXCLUDED_THING_LABELS',
    'MEMORY_INVALID_TAKEN_AT_DATE',
    'MEMORY_PLAN_MIN_FILE_COUNT',
    'INSUFFICIENT_MEMORY_PHOTOS_MESSAGE',
]
