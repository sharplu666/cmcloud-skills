#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件分类桶：取 ``File.category``。

``category`` 由后端根据后缀名和 mime-type 分类，枚举值有：
``app`` / ``zip`` / ``image`` / ``doc`` / ``video`` / ``audio`` /
``folder`` / ``others``。

空值/纯空白 → ``UNKNOWN``。
"""

from __future__ import annotations

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


@register_bucket('category')
class CategoryBucketer(Bucketer):
    """按文件分类分桶，取 ``File.category``，如 ``"image"`` / ``"video"``。"""

    bucket_category = 'attr'
    bucket_label = '文件分类'

    def bucket_key(self, f: File) -> str:
        c = f.category
        return c.strip() if isinstance(c, str) and c.strip() else UNKNOWN_BUCKET
