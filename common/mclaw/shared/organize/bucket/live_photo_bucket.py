#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态照片桶：取 ``File.media_meta_info.live_photo``。

``live_photo`` 为布尔值：
    - ``True``  → ``"live"``（动态照片）
    - ``False`` → ``"static"``（静态照片）

当 ``media_meta_info`` 整体缺失（无法判断拍摄设备是否上报）时归入 ``UNKNOWN``，
与「明确上报为静态」区分开。
"""

from __future__ import annotations

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


@register_bucket('livePhoto')
class LivePhotoBucketer(Bucketer):
    """按是否动态照片分桶：``"live"`` / ``"static"`` / ``"UNKNOWN"``。"""

    bucket_category = 'attr'
    bucket_label = '动态照片'
    # ``File.media_meta_info.live_photo`` 仅对图片文件有意义；视频/文档等无此属性
    applicable_file_categories = ('image',)

    def bucket_key(self, f: File) -> str:
        m = f.media_meta_info
        if m is None:
            return UNKNOWN_BUCKET
        return 'live' if m.live_photo else 'static'
