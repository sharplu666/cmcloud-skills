#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件扩展名桶：取 ``File.file_extension``。

``file_extension`` 一般是后缀名（不区分大小写），如 ``"jpg"`` / ``"png"`` /
``"mp4"`` / ``"pdf"``。本桶统一小写化以便聚合。

空值/纯空白 → ``UNKNOWN``。
"""

from __future__ import annotations

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


@register_bucket('fileExtension')
class FileExtensionBucketer(Bucketer):
    """按扩展名分桶，统一小写，如 ``"jpg"`` / ``"mp4"``。"""

    bucket_category = 'attr'
    bucket_label = '扩展名'

    def bucket_key(self, f: File) -> str:
        ext = f.file_extension
        ext = ext.strip().lower() if isinstance(ext, str) else ''
        return ext if ext else UNKNOWN_BUCKET
