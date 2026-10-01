#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AOI 地标维度桶（单值）。

参考 ``File.address_detail.location_aoi``（接口 alias ``locationAoi``），
其中每个 ``LocationAoi`` 项含 ``name`` / ``subType`` / ``subTypeName`` / ``area``。

取值规则（由产品指定）：

1. **全部 ``area`` 为空（缺失或不可解析为 float）** → 取接口 ``array`` 的第一项
2. **存在非空 ``area``** → 取最大 ``area`` 对应项；若有并列最大，取数组里靠前的那个
3. 最终返回被选中项的 ``name`` 字段（单值 ``str``）

空值/纯空白/空数组/缺失 ``name`` → 归入 ``UNKNOWN`` 桶。
"""

from __future__ import annotations

import math
from typing import Any, List, Optional

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


def _area_of(item: Any) -> Optional[float]:
    """把 ``LocationAoi.area``（字符串，平方米）解析成 ``float``。

    缺失 / 空串 / 非数值 / NaN → 返回 ``None``，与「全部 area 为空」判定保持一致。
    """
    raw = getattr(item, 'area', None)
    if not raw:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _pick_aoi_name(items: List[Any]) -> str:
    """按规则从 ``location_aoi`` 列表里选出 ``name``。

    - 空列表 → 返回空串（由 ``bucket_key`` 兜底为 ``UNKNOWN_BUCKET``）
    - 全部 area 为空 → 第一项的 name
    - 否则 → 最大 area 的第一项的 name
    """
    if not items:
        return ''
    areas = [_area_of(x) for x in items]
    if all(a is None for a in areas):
        chosen = items[0]
    else:
        max_area = max(a for a in areas if a is not None)
        chosen = next(items[i] for i, a in enumerate(areas) if a == max_area)
    name = getattr(chosen, 'name', '') or ''
    return name.strip()


@register_bucket('locationAoi')
class LocationAoiBucketer(Bucketer):
    """按 AOI 地标分桶（单值），取 ``address_detail.location_aoi`` 中按 area 规则筛选后的 name。"""

    bucket_category = 'location'
    bucket_label = '地标/AOI'

    def bucket_key(self, f: File) -> str:
        addr = f.address_detail
        if not addr:
            return UNKNOWN_BUCKET
        items = addr.location_aoi or []
        name = _pick_aoi_name(items)
        return name if name else UNKNOWN_BUCKET
