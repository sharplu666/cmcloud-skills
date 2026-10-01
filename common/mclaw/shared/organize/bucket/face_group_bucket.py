#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单人照/双人照/多人照桶：基于 ``len(ai_analysis_info.face_info_list)`` 归类。

规则：
    - ``ai_analysis_info`` 缺失 → ``UNKNOWN``（无法判断）
    - ``face_info_list`` 为空 → ``UNKNOWN``（不再单独归为“无人照”）
    - ``face_info_list`` 长度为 1 → ``"单人照"``
    - ``face_info_list`` 长度为 2 → ``"双人照"``
    - ``face_info_list`` 长度 >= 3 → ``"多人照"``
"""

from __future__ import annotations

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


@register_bucket('faceGroup')
class FaceGroupBucketer(Bucketer):
    """按人脸数量区分 ``单人照`` / ``双人照`` / ``多人照``；0 人脸归 ``UNKNOWN``。"""

    bucket_category = 'attr'
    bucket_label = '照片单/双/多人'
    applicable_file_categories = ('image',)

    def bucket_key(self, f: File) -> str:
        ai = f.ai_analysis_info
        if ai is None:
            return UNKNOWN_BUCKET
        face_count = len(ai.face_info_list)
        if face_count <= 0:
            return UNKNOWN_BUCKET
        if face_count == 1:
            return '单人照'
        if face_count == 2:
            return '双人照'
        return '多人照'
