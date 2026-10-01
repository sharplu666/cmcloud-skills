#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地点维度桶。

参考 ``File.address_detail`` 结构，地点维度包含：

    - 单值字段：``country`` / ``province`` / ``city`` / ``district`` / ``township``
    - 多值字段：``location_names``（具体位置/景点列表）

本模块提供 ``_LocationBase`` 基类，统一按 ``field`` 类属性从
``File.address_detail`` 取值：

    - 单值地点桶返回 ``str``
    - 多值地点桶返回 ``list[str]``

各粒度分别注册成独立桶名（``country`` / ``province`` / ``city`` /
``district`` / ``township``），外加一个 ``location`` 桶作为默认入口（等价于
``city``，供用户未明确指定粒度时使用）。

``address_detail.location_names`` 为旧格式多值字段，不再注册为独立桶；景点维度请用
``locationAoi``（见 ``location_aoi_bucket``）。

空值/纯空白/非字符串 → 归入 ``UNKNOWN`` 桶；
多值字段空列表/清洗后为空 → 归入 ``['UNKNOWN']``。
"""

from __future__ import annotations

from typing import List, Union

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


#: address_detail 支持的地点粒度字段（``AddressDetail`` snake_case 属性名）
SUPPORTED_LOCATION_FIELDS: tuple[str, ...] = (
    'country', 'province', 'city', 'district', 'township',
)

#: 默认地点粒度（用户未明确指定时使用）
DEFAULT_LOCATION_FIELD: str = 'city'


class _LocationBase(Bucketer):
    """地点桶基类：按 ``field`` 类属性从 ``address_detail`` 取值。

    单值地点桶从 ``address_detail`` 读取对应 ``field``；``is_multi_value`` 子类可扩展多值逻辑。
    """

    field: str = DEFAULT_LOCATION_FIELD

    def bucket_key(self, f: File) -> Union[str, List[str]]:
        if self.is_multi_value:
            addr = f.address_detail
            if addr is None:
                return [UNKNOWN_BUCKET]
            # ``AddressDetail.location_names`` 在 Pydantic 模型中为
            # ``Optional[List[str]]``，缺失时为 ``None``（非空 list），这里兜底为 []。
            raw = getattr(addr, self.field, None) or []
            cleaned = [
                str(x).strip()
                for x in raw
                if isinstance(x, str) and str(x).strip()
            ]
            return cleaned or [UNKNOWN_BUCKET]

        addr = f.address_detail
        if not addr:
            return UNKNOWN_BUCKET
        v = getattr(addr, self.field, '')
        return v.strip() if isinstance(v, str) and v.strip() else UNKNOWN_BUCKET


@register_bucket('location')
class LocationBucketer(_LocationBase):
    """默认地点桶：取 ``city``。

    用户未明确指定地点粒度（如「按地点整理」「每个地点挑 2 张」）时使用本桶。
    等价于 ``CityBucketer``。
    """

    bucket_category = 'location'
    bucket_label = '地点（默认城市）'

    field = 'city'


@register_bucket('country')
class CountryBucketer(_LocationBase):
    """按国家分桶，取 ``address_detail.country``。"""

    bucket_category = 'location'
    bucket_label = '国家'

    field = 'country'


@register_bucket('province')
class ProvinceBucketer(_LocationBase):
    """按省份分桶，取 ``address_detail.province``。"""

    bucket_category = 'location'
    bucket_label = '省份'

    field = 'province'


@register_bucket('city')
class CityBucketer(_LocationBase):
    """按城市分桶，取 ``address_detail.city``。

    地点维度默认粒度：用户说「按地点」但未指定粒度时，``resolve_dimensions(['location'])``
    返回 ``['city']``。
    """

    bucket_category = 'location'
    bucket_label = '城市'
    is_default_in_bucket_category = True   # 地点维度默认粒度

    field = 'city'


@register_bucket('district')
class DistrictBucketer(_LocationBase):
    """按区县分桶，取 ``address_detail.district``。"""

    bucket_category = 'location'
    bucket_label = '区县'

    field = 'district'


@register_bucket('township')
class TownshipBucketer(_LocationBase):
    """按乡镇/街道分桶，取 ``address_detail.township``。"""

    bucket_category = 'location'
    bucket_label = '乡镇/街道'

    field = 'township'
