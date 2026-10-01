#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间维度桶：``day`` / ``week`` / ``month`` / ``year``。

时间取值优先级链：``taken_at → local_created_at → created_at``
（来自 ``File.media_meta_info.taken_at`` → ``File.local_created_at`` → ``File.created_at``）。
字段优先级定义见本模块 ``TIME_FIELD_PRIORITY``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


#: 时间字段优先级链：拍摄时间 > 本地创建 > 服务端创建
TIME_FIELD_PRIORITY: tuple[str, ...] = ('takenAt', 'localCreatedAt', 'createdAt')

#: 已注册的时间桶名（桶名即粒度）
TIME_BUCKET_NAMES: tuple[str, ...] = ('day', 'week', 'month', 'year')

#: 时间粒度 → strftime 模板（``week`` 使用 ISO 周，见 ``_week_key``）
_TIME_FORMATS: dict[str, str] = {
    'day': '%Y-%m-%d',
    'month': '%Y-%m',
    'year': '%Y',
}


def _parse_time_string(raw: str) -> Optional[datetime]:
    """解析时间字符串，支持 RFC3339 与 merge 搜图归一化后的 yyyyMMddHHmmss。"""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if len(text) == 14 and text.isdigit():
        try:
            return datetime(
                int(text[0:4]),
                int(text[4:6]),
                int(text[6:8]),
                int(text[8:10]),
                int(text[10:12]),
                int(text[12:14]),
            )
        except ValueError:
            return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def resolve_time_value(file_: File) -> Optional[datetime]:
    """按优先级链取时间：``takenAt → localCreatedAt → createdAt``。

    ``TIME_FIELD_PRIORITY`` 用源 API 字段名（camelCase）以便阅读；
    ``_FIELD_TO_ATTR`` 将其映射到 Pydantic ``File`` 的 snake_case 属性名。
    """
    for field_name in TIME_FIELD_PRIORITY:
        attr = _FIELD_TO_ATTR[field_name]
        if attr == 'taken_at':
            raw = file_.media_meta_info.taken_at if file_.media_meta_info else ''
        else:
            raw = getattr(file_, attr, '') or ''
        dt = _parse_time_string(raw)
        if dt is not None:
            return dt
    return None


#: ``TIME_FIELD_PRIORITY``（源 API camelCase 字段名）→ Pydantic ``File`` snake_case 属性
_FIELD_TO_ATTR: dict[str, str] = {
    'takenAt': 'taken_at',          # File.media_meta_info.taken_at（特殊路径）
    'localCreatedAt': 'local_created_at',
    'createdAt': 'created_at',
}


def _time_key(f: File, fmt: str) -> str:
    dt = resolve_time_value(f)
    return dt.strftime(fmt) if dt else UNKNOWN_BUCKET


def _week_key(f: File) -> str:
    """ISO 8601 周：``YYYY-Www``（周一为一周起始）。"""
    dt = resolve_time_value(f)
    if dt is None:
        return UNKNOWN_BUCKET
    iso_year, iso_week, _ = dt.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def _upload_week_key(f: File) -> str:
    """上传时间 ISO 周（仅 ``created_at``）。"""
    dt = _parse_time_string(f.created_at)
    if dt is None:
        return UNKNOWN_BUCKET
    iso_year, iso_week, _ = dt.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


# ----------------------------------------------------------------------
# 时间优先级桶（takenAt → localCreatedAt → createdAt 优先级链）
# ----------------------------------------------------------------------

@register_bucket('day')
class DayBucketer(Bucketer):
    """按天分桶，key 形如 ``"2026-05-18"``。"""

    bucket_category = 'time'
    bucket_label = '日'

    def bucket_key(self, f: File) -> str:
        return _time_key(f, _TIME_FORMATS['day'])


@register_bucket('week')
class WeekBucketer(Bucketer):
    """按 ISO 周分桶，key 形如 ``"2026-W20"``。"""

    bucket_category = 'time'
    bucket_label = '周'

    def bucket_key(self, f: File) -> str:
        return _week_key(f)


@register_bucket('month')
class MonthBucketer(Bucketer):
    """按月分桶，key 形如 ``"2026-05"``。"""

    bucket_category = 'time'
    bucket_label = '月'
    is_default_in_bucket_category = True   # 时间维度默认粒度：用户说「按时间」但未指定粒度时用 month

    def bucket_key(self, f: File) -> str:
        return _time_key(f, _TIME_FORMATS['month'])


@register_bucket('year')
class YearBucketer(Bucketer):
    """按年分桶，key 形如 ``"2026"``。"""

    bucket_category = 'time'
    bucket_label = '年'

    def bucket_key(self, f: File) -> str:
        return _time_key(f, _TIME_FORMATS['year'])


# ----------------------------------------------------------------------
# 显式拍摄时间桶（仅 takenAt，不走优先级链）
# ----------------------------------------------------------------------

def _taken_time_key(f: File, fmt: str) -> str:
    """仅从 ``taken_at`` 取值，不 fallback 到 local_created_at / created_at。"""
    raw = f.media_meta_info.taken_at if f.media_meta_info else ''
    dt = _parse_time_string(raw)
    return dt.strftime(fmt) if dt else UNKNOWN_BUCKET


def _taken_week_key(f: File) -> str:
    """拍摄时间 ISO 周（仅 ``taken_at``）。"""
    raw = f.media_meta_info.taken_at if f.media_meta_info else ''
    dt = _parse_time_string(raw)
    if dt is None:
        return UNKNOWN_BUCKET
    iso_year, iso_week, _ = dt.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


@register_bucket('takenDay')
class TakenDayBucketer(Bucketer):
    """按拍摄日期分桶（仅 takenAt），key 形如 ``"2026-05-18"``。"""

    bucket_category = 'time'
    bucket_label = '拍摄日'

    def bucket_key(self, f: File) -> str:
        return _taken_time_key(f, _TIME_FORMATS['day'])


@register_bucket('takenWeek')
class TakenWeekBucketer(Bucketer):
    """按拍摄 ISO 周分桶（仅 takenAt），key 形如 ``"2026-W20"``。"""

    bucket_category = 'time'
    bucket_label = '拍摄周'

    def bucket_key(self, f: File) -> str:
        return _taken_week_key(f)


@register_bucket('takenMonth')
class TakenMonthBucketer(Bucketer):
    """按拍摄月份分桶（仅 takenAt），key 形如 ``"2026-05"``。"""

    bucket_category = 'time'
    bucket_label = '拍摄月'

    def bucket_key(self, f: File) -> str:
        return _taken_time_key(f, _TIME_FORMATS['month'])


@register_bucket('takenYear')
class TakenYearBucketer(Bucketer):
    """按拍摄年份分桶（仅 takenAt），key 形如 ``"2026"``。"""

    bucket_category = 'time'
    bucket_label = '拍摄年'

    def bucket_key(self, f: File) -> str:
        return _taken_time_key(f, _TIME_FORMATS['year'])


# ----------------------------------------------------------------------
# 上传时间桶（仅 createdAt，不走优先级链）
# ----------------------------------------------------------------------

def _upload_time_key(f: File, fmt: str) -> str:
    """仅从 ``created_at`` 取值，不 fallback 到拍摄时间。"""
    dt = _parse_time_string(f.created_at)
    return dt.strftime(fmt) if dt else UNKNOWN_BUCKET


@register_bucket('uploadDay')
class UploadDayBucketer(Bucketer):
    """按上传日期分桶（仅 createdAt），key 形如 ``"2026-05-18"``。"""

    bucket_category = 'time'
    bucket_label = '上传日'

    def bucket_key(self, f: File) -> str:
        return _upload_time_key(f, _TIME_FORMATS['day'])


@register_bucket('uploadWeek')
class UploadWeekBucketer(Bucketer):
    """按上传 ISO 周分桶（仅 createdAt），key 形如 ``"2026-W20"``。"""

    bucket_category = 'time'
    bucket_label = '上传周'

    def bucket_key(self, f: File) -> str:
        return _upload_week_key(f)


@register_bucket('uploadMonth')
class UploadMonthBucketer(Bucketer):
    """按上传月份分桶（仅 createdAt），key 形如 ``"2026-05"``。"""

    bucket_category = 'time'
    bucket_label = '上传月'

    def bucket_key(self, f: File) -> str:
        return _upload_time_key(f, _TIME_FORMATS['month'])


@register_bucket('uploadYear')
class UploadYearBucketer(Bucketer):
    """按上传年份分桶（仅 createdAt），key 形如 ``"2026"``。"""

    bucket_category = 'time'
    bucket_label = '上传年'

    def bucket_key(self, f: File) -> str:
        return _upload_time_key(f, _TIME_FORMATS['year'])


# ----------------------------------------------------------------------
# 更新时间桶（仅 updatedAt，不走优先级链）
# ----------------------------------------------------------------------

def _update_time_key(f: File, fmt: str) -> str:
    """仅从 ``updated_at`` 取值，不 fallback 到 created_at / taken_at。"""
    dt = _parse_time_string(f.updated_at)
    return dt.strftime(fmt) if dt else UNKNOWN_BUCKET


def _update_week_key(f: File) -> str:
    """更新时间 ISO 周（仅 ``updated_at``）。"""
    dt = _parse_time_string(f.updated_at)
    if dt is None:
        return UNKNOWN_BUCKET
    iso_year, iso_week, _ = dt.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


@register_bucket('updateDay')
class UpdateDayBucketer(Bucketer):
    """按更新日期分桶（仅 updatedAt），key 形如 ``"2026-05-18"``。"""

    bucket_category = 'time'
    bucket_label = '更新日'

    def bucket_key(self, f: File) -> str:
        return _update_time_key(f, _TIME_FORMATS['day'])


@register_bucket('updateWeek')
class UpdateWeekBucketer(Bucketer):
    """按更新 ISO 周分桶（仅 updatedAt），key 形如 ``"2026-W20"``。"""

    bucket_category = 'time'
    bucket_label = '更新周'

    def bucket_key(self, f: File) -> str:
        return _update_week_key(f)


@register_bucket('updateMonth')
class UpdateMonthBucketer(Bucketer):
    """按更新月份分桶（仅 updatedAt），key 形如 ``"2026-05"``。"""

    bucket_category = 'time'
    bucket_label = '更新月'

    def bucket_key(self, f: File) -> str:
        return _update_time_key(f, _TIME_FORMATS['month'])


@register_bucket('updateYear')
class UpdateYearBucketer(Bucketer):
    """按更新年份分桶（仅 updatedAt），key 形如 ``"2026"``。"""

    bucket_category = 'time'
    bucket_label = '更新年'

    def bucket_key(self, f: File) -> str:
        return _update_time_key(f, _TIME_FORMATS['year'])
