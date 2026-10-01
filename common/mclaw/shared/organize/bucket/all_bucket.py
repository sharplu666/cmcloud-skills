#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全部归一桶：所有文件进入**同一个桶**，不做任何聚类。

用于「只搜图、不分维度」的场景：

- 生成相册：``一次搜图 = 一册`` 的天然对应（见 ``ORGANIZE-PHOTO.md``）
- 预搜索画像：只看总量与 fileId 去重统计，不按维度拆分
- 多维聚类的对照基线：先 ``--bucket all`` 看全量画像，再决定是否细分

设计要点：

- ``bucket_key`` 对任意 ``File`` 返回**常量** ``'ALL'``，``distinct_count`` 恒为 1
- 不读取任何字段，故对 ``UNKNOWN`` 缺失值不敏感（不会产生 UNKNOWN 桶）
- ``applicable_file_categories`` 为空，对所有文件类型生效
"""

from __future__ import annotations

from typing import final

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer
from mclaw.shared.organize.bucket.registry import register_bucket


#: 单一桶名常量。所有文件归入此桶。
ALL_BUCKET: str = 'ALL'


@register_bucket('all')
class AllBucketer(Bucketer):
    """所有文件归入同一个桶（``ALL``），不做聚类。

    ``bucket_key`` 恒返回 :data:`ALL_BUCKET`，与 ``File`` 字段无关。
    ``distinct_count`` 恒为 1，``too_many`` 恒为 False。
    """

    bucket_category = 'misc'
    bucket_label = '全部（不聚类）'
    is_default_in_bucket_category = True

    @final
    def bucket_key(self, f: File) -> str:  # noqa: ARG002
        return ALL_BUCKET
