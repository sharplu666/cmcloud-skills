#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人脸数量桶：取 ``len(ai_analysis_info.face_info_list)``，格式化为 ``N人照``。

参考 ``File.ai_analysis_info.face_info_list``：
    - ``ai_analysis_info`` 缺失 → ``UNKNOWN``（无法判断）
    - 存在但 ``face_info_list`` 为空 → ``UNKNOWN``（无法判断）
    - 否则桶 key 为 ``"1人照"`` / ``"2人照"`` / ...
"""

from __future__ import annotations

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


@register_bucket('faceCount')
class FaceCountBucketer(Bucketer):
    """按检测到的人脸数量分桶（``face_info_list`` 数组长度，key 形如 ``N人照``）。"""

    bucket_category = 'attr'
    bucket_label = '人脸数量'
    applicable_file_categories = ('image',)

    def bucket_key(self, f: File) -> str:
        ai = f.ai_analysis_info
        if ai is None:
            return UNKNOWN_BUCKET
        if not ai.face_info_list:
            return UNKNOWN_BUCKET
        return f'{len(ai.face_info_list)}人照'
