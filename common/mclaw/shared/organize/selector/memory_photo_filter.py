#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回忆故事图片过滤（相似图去重前，File 级）。

1:1 移植 ``cm_cloud_organize/scripts/memory_photo_filter.py``，适配 common
``mclaw.api.search_fusion.File``（Pydantic v2，snake_case 字段）。

职责：相似图去重**之前**，剔除不宜收录进回忆故事的图片：
  - 事物标签命中黑名单（证件 / 截图 / 卡通 / 文档 …）
  - 无拍摄时间，或拍摄时间为 1970-01-01

不持鉴权/host、不发 HTTP：纯本地过滤。

权威来源：``cm_cloud_organize/scripts/memory_photo_filter.py``。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from mclaw.api.search_fusion import File

try:
    from cli_timing import write_cli_output_line
except ImportError:
    def write_cli_output_line(line: str) -> None:
        print(line, flush=True)


__all__ = [
    'MemoryPhotoFilter',
    'MEMORY_EXCLUDED_THING_LABELS',
    'MEMORY_INVALID_TAKEN_AT_DATE',
    'MEMORY_PLAN_MIN_FILE_COUNT',
    'INSUFFICIENT_MEMORY_PHOTOS_MESSAGE',
]


# 任一 thing_label_list.name 命中即排除（精确匹配）
MEMORY_EXCLUDED_THING_LABELS: frozenset[str] = frozenset({
    '卡通',
    '文档',
    '证件',
    '其他证件',
    '身份证',
    '银行卡',
    '社保卡',
    '港澳通行证',
    '驾驶证',
    '行驶证',
    '护照',
    '居住证',
    '学生证',
    '户口本',
    '房产证',
    '营业执照',
    '截图',
})

MEMORY_INVALID_TAKEN_AT_DATE = '1970-01-01'
#: 回忆故事最低素材数（单张即可成故事，2026-08-31 用户定案由 2 放宽）
MEMORY_PLAN_MIN_FILE_COUNT = 1
INSUFFICIENT_MEMORY_PHOTOS_MESSAGE = '无合适的入选照片'


def _taken_at_calendar_date(raw: str) -> str:
    """将 takenAt 归一化为 ``YYYY-MM-DD``；无法解析时返回空串。"""
    s = (raw or '').strip()
    if not s:
        return ''
    if len(s) >= 8 and s[:8].isdigit():
        return f'{s[0:4]}-{s[4:6]}-{s[6:8]}'
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    return ''


def _file_taken_at_raw(file_: File) -> str:
    """取 ``media_meta_info.taken_at``（仅拍摄时间，不回退 createdAt）。"""
    media = file_.media_meta_info
    if not media:
        return ''
    return (media.taken_at or '').strip()


class MemoryPhotoFilter:
    """回忆故事图片去重前过滤器（事物标签 + 拍摄时间）。

    纯本地过滤，不触网。``filter`` 先按事物标签、再按拍摄时间剔除；
    ``ensure_sufficient`` 校验过滤后入选数 ≥ ``MEMORY_PLAN_MIN_FILE_COUNT``。
    """

    def is_excluded_by_thing_label(self, file_: File) -> bool:
        """文件是否含需排除的事物标签（任一 thing_label_list.name 命中黑名单）。"""
        ai = file_.ai_analysis_info
        if not ai or not ai.thing_label_list:
            return False
        for label in ai.thing_label_list:
            name = (label.name or '').strip()
            if name in MEMORY_EXCLUDED_THING_LABELS:
                return True
        return False

    def is_invalid_taken_at(self, file_: File) -> bool:
        """无拍摄时间，或拍摄日期为 1970-01-01。"""
        raw = _file_taken_at_raw(file_)
        if not raw:
            return True
        return _taken_at_calendar_date(raw) == MEMORY_INVALID_TAKEN_AT_DATE

    def filter(self, files: List[File]) -> Tuple[List[File], Dict[str, int]]:
        """回忆故事去重前过滤（事物标签 → 拍摄时间）。返回 ``(保留 files, 统计)``。"""
        kept, thing_removed = self._filter_excluded_thing_label(files)
        kept, taken_removed = self._filter_invalid_taken_at(kept)
        return kept, {
            'thing_label_filtered_removed': thing_removed,
            'taken_at_filtered_removed': taken_removed,
        }

    def ensure_sufficient(self, files: List[File]) -> None:
        """过滤与去重后入选数须 ≥ ``MEMORY_PLAN_MIN_FILE_COUNT``，否则抛 ``ValueError``。"""
        if len(files) < MEMORY_PLAN_MIN_FILE_COUNT:
            write_cli_output_line(INSUFFICIENT_MEMORY_PHOTOS_MESSAGE)
            raise ValueError(INSUFFICIENT_MEMORY_PHOTOS_MESSAGE)

    # ──────────────────────────── 内部 ────────────────────────────

    def _filter_excluded_thing_label(self, files: List[File]) -> Tuple[List[File], int]:
        """按事物标签过滤。返回 ``(保留 files, 移除张数)``。"""
        kept = [f for f in files if not self.is_excluded_by_thing_label(f)]
        return kept, len(files) - len(kept)

    def _filter_invalid_taken_at(self, files: List[File]) -> Tuple[List[File], int]:
        """按拍摄时间过滤。返回 ``(保留 files, 移除张数)``。"""
        kept = [f for f in files if not self.is_invalid_taken_at(f)]
        return kept, len(files) - len(kept)
