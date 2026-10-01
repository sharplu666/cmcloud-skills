#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云搜索入参构建与分页游标规范化（纯函数）。

权威常量见模块内 ``DEFAULT_SEARCH_SIZE_*`` / ``SIZE_FILTER_FILE_TYPES``。

用法::

    from mclaw.shared.postprocess.search_param import (
        build_search_file_param_v3,
        normalize_page_after_input,
        page_after_to_cli_cursor,
    )

    param = build_search_file_param_v3(
        keyword='发票',
        file_types=[4],
        start_at='2024-01-01',
        end_at='2024-12-31',
        size_range={'start': 1024, 'end': 10_000_000},
    )
    page_after = normalize_page_after_input(cli_cursor)
    next_cursor = page_after_to_cli_cursor(api_page_after)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mclaw.shared.cm_cloud.transforms import parse_date_range_value

#: 搜索 sizeRange 默认下限（字节）
DEFAULT_SEARCH_SIZE_MIN = 0
#: 搜索 sizeRange 默认上限（字节）
DEFAULT_SEARCH_SIZE_MAX = 10 * (1 << 40)
#: 支持按文件大小区间筛选的类型（不含目录 5）
SIZE_FILTER_FILE_TYPES = [1, 2, 3, 4, 6]


def normalize_page_after_input(page_after: Optional[Any]) -> Optional[List[Any]]:
    """将 CLI ``--page-cursor`` 入参规范为 merge 搜索的 pageInfo.pageAfter 列表。"""
    if page_after is None:
        return None
    if isinstance(page_after, list):
        return page_after or None
    if isinstance(page_after, dict):
        return [page_after]
    s = str(page_after).strip()
    return [s] if s else None


def page_after_to_cli_cursor(page_after: Any) -> Optional[str]:
    """将 API 返回的 pageAfter 转为 CLI 可直接传入 ``--page-cursor`` 的纯游标字符串。"""
    if page_after is None or page_after == '':
        return None
    if isinstance(page_after, list):
        if len(page_after) == 1 and page_after[0] is not None:
            return str(page_after[0]).strip() or None
        return None
    s = str(page_after).strip()
    return s or None


def build_search_file_param_v3(
    *,
    keyword: str = '',
    file_types: Optional[List[int]] = None,
    extension: Optional[str] = None,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    time_field: str = 'updatedAt',
    address_list: Optional[List[str]] = None,
    thing_list: Optional[List[str]] = None,
    include_file_id_list: Optional[List[str]] = None,
    exclude_file_id_list: Optional[List[str]] = None,
    recursion: Optional[bool] = None,
    size_range: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """根据 CLI 入参构建 SearchFileParamV3 字典。

    Raises:
        ValueError: file_type / time_field / sizeRange / id 列表超限等不合法时。
    """
    effective_types: List[int] = (
        list(dict.fromkeys(int(t) for t in file_types)) if file_types else []
    )
    invalid_types = [t for t in effective_types if t not in {0, 1, 2, 3, 4, 5, 6}]
    if invalid_types:
        raise ValueError(
            f'非法 file_type: {invalid_types}，仅支持 0综合/1图片/2音频/3视频/4文档/5目录/6其他'
        )

    param: Dict[str, Any] = {}
    if effective_types:
        param['typeList'] = effective_types
    if keyword:
        param['nameList'] = [keyword]
    if extension:
        param['suffixList'] = [str(extension).strip().lstrip('.').lower()]
    if address_list:
        param['addressList'] = [str(x).strip() for x in address_list if str(x).strip()][:10]
    if thing_list:
        param['thingList'] = [str(x).strip() for x in thing_list if str(x).strip()][:10]

    if include_file_id_list:
        include_ids = list(
            dict.fromkeys(str(x).strip() for x in include_file_id_list if str(x).strip())
        )
        if include_ids:
            if len(include_ids) > 20:
                raise ValueError('includeFileIdList 最多支持 20 个目录 id')
            param['includeFileIdList'] = include_ids

    if size_range:
        if 5 in effective_types:
            raise ValueError('sizeRange 不支持目录类型（file_type=5）')
        if not effective_types:
            param['typeList'] = list(SIZE_FILTER_FILE_TYPES)
        size_payload: Dict[str, int] = {}
        if size_range.get('start') is not None:
            size_payload['startSize'] = int(size_range['start'])
        if size_range.get('end') is not None:
            size_payload['endSize'] = int(size_range['end'])
        if size_payload:
            size_payload.setdefault('startSize', DEFAULT_SEARCH_SIZE_MIN)
            size_payload.setdefault('endSize', DEFAULT_SEARCH_SIZE_MAX)
            param['sizeRange'] = size_payload

    if time_field not in ('createdAt', 'updatedAt', 'takenAt'):
        raise ValueError('非法 time_field，仅支持 createdAt / updatedAt / takenAt')
    if time_field == 'takenAt':
        if effective_types and set(effective_types) != {1}:
            raise ValueError('takenAt 仅支持图片类型，请仅传 --file-type 1')
        if not effective_types:
            param['typeList'] = [1]
    if start_at and end_at:
        param['timeList'] = [{
            # API 字段名即为 filed（非 field），与接口契约一致
            'filed': time_field,
            'startAt': parse_date_range_value(start_at, end=False),
            'endAt': parse_date_range_value(end_at, end=True),
        }]

    if exclude_file_id_list:
        exclude_ids = list(
            dict.fromkeys(str(x).strip() for x in exclude_file_id_list if str(x).strip())
        )
        if exclude_ids:
            if len(exclude_ids) > 20:
                raise ValueError('excludeFileIdList 最多支持 20 个目录 id')
            param['excludeFileIdList'] = exclude_ids

    if recursion is not None:
        param['recursion'] = bool(recursion)

    param.setdefault('typeList', [0])
    return param


__all__ = [
    'DEFAULT_SEARCH_SIZE_MIN',
    'DEFAULT_SEARCH_SIZE_MAX',
    'SIZE_FILTER_FILE_TYPES',
    'normalize_page_after_input',
    'page_after_to_cli_cursor',
    'build_search_file_param_v3',
]
