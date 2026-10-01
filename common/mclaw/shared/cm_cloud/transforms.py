#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云盘纯数据转换 —— 时间、分类、日期范围、播放进度。

无 HTTP / 鉴权 / 状态，仅依赖标准库；供各 skill Service 层与 CLI 工具函数复用。
"""

from __future__ import annotations

import calendar
import re
from typing import Any

SEARCH_CATEGORY_TO_EN: dict[str, str] = {
    '0': 'others',  # 综合（兼容，API 响应一般直接用英文 token）
    '1': 'image',
    '2': 'audio',
    '3': 'video',
    '4': 'doc',
    '5': 'folder',
    '6': 'others',
}

_SEARCH_CATEGORY_EN_TOKENS = frozenset(SEARCH_CATEGORY_TO_EN.values())


def normalize_search_category(cat_raw: str) -> str:
    """接口 category 码或已是英文 token -> 管道内英文类型。"""
    c = str(cat_raw or '').strip().lower()
    if c in _SEARCH_CATEGORY_EN_TOKENS:
        return c
    return SEARCH_CATEGORY_TO_EN.get(c, 'others')


def cloud_asset_time_to_skill14(raw: Any) -> str:
    """将 RFC3339/ISO 时间或已是 14 位数字的时间字符串转为 yyyyMMddHHmmss。"""
    s = str(raw or '').strip()
    if not s:
        return ''
    if len(s) == 14 and s.isdigit():
        return s
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})', s)
    if m:
        return f'{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{m.group(5)}{m.group(6)}'
    return s


def parse_date_range_value(s: str, *, end: bool) -> str:
    """解析搜索/列举时间参数，格式化为 API 要求的 yyyyMMddHHmmss。

    支持：yyyyMMddHHmmss、yyyyMM、yyyyMMdd、YYYY-MM、YYYY-M、YYYY-MM-DD、YYYY-M-D，
    以及斜杠分隔的同等写法（如 2025/01/15）。按月筛选时，结束时间取该月最后一天。
    """
    s = str(s or '').strip()
    if not s:
        raise ValueError('时间参数不能为空')

    if len(s) == 14 and s.isdigit():
        return s

    if '/' not in s and '-' not in s:
        compact = s
        if compact.isdigit() and len(compact) in (6, 8):
            if len(compact) == 6:
                y, m = int(compact[:4]), int(compact[4:6])
                if not 1 <= m <= 12:
                    raise ValueError(f'无法解析日期: {s!r}（月份须在 1–12）')
                if end:
                    last_day = calendar.monthrange(y, m)[1]
                    return f'{y:04d}{m:02d}{last_day:02d}235959'
                return f'{y:04d}{m:02d}01000000'
            return f'{compact}{"235959" if end else "000000"}'

    s = s.replace('/', '-')
    parts = [p for p in s.split('-') if p.strip()]
    if len(parts) == 2:
        y, m = int(parts[0]), int(parts[1])
        if end:
            return f'{y:04d}{m:02d}{calendar.monthrange(y, m)[1]:02d}235959'
        return f'{y:04d}{m:02d}01000000'
    if len(parts) >= 3:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f'{y:04d}{m:02d}{d:02d}{"235959" if end else "000000"}'

    raise ValueError(
        f'无法解析日期: {s!r}（请使用 YYYY-MM、YYYY-MM-DD、yyyyMM、yyyyMMdd 或 yyyyMMddHHmmss）'
    )


def parse_playback_milliseconds(raw: Any) -> int:
    """将接口返回的播放进度毫秒数转为秒（异常时返回 0）。"""
    try:
        return int(float(str(raw or 0)) / 1000)
    except (ValueError, TypeError):
        return 0
