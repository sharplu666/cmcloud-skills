#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-transfer 参数校验（口径见 docs/cli_design.md §10.1）。

参数仅 6 个（keyword/start-at/end-at/transfer-type/page-size/page-after），全裸
字符串收参；时间复用 ``services/search/args`` 的宽容解析与上限口径（戒律 12：
时间口径单一来源，勿在本模块另写一套）。
"""

from __future__ import annotations

from dataclasses import dataclass

from services.errors import CliValidationError
from services.search.args import (
    _enforce_time_ceiling,
    _now_14,
    format_datetime19,
    parse_time_14,
)

__all__ = [
    'TRANSFER_TYPE_LABELS',
    'TRANSFER_TYPE_HINT',
    'DEFAULT_PAGE_SIZE',
    'PAGE_SIZE_MAX',
    'SearchTransferArgs',
    'validate_search_transfer',
]

#: 转存类型 → 用户向标签（wire dynamicType 单值）
TRANSFER_TYPE_LABELS = {5: '分享转存', 6: '圈子转存', 7: '发现转存'}
#: 报错/帮助共用的取值提示（单次只查一种）
TRANSFER_TYPE_HINT = '5=分享转存 / 6=圈子转存 / 7=发现转存（单次只查一种）'

DEFAULT_PAGE_SIZE = 10
PAGE_SIZE_MAX = 100


@dataclass(frozen=True)
class SearchTransferArgs:
    """校验后的 search-transfer 入参（时间已固化为 wire 19 位绝对值）。"""

    keyword: str
    start_at: str      # yyyy-MM-dd HH:mm:ss
    end_at: str        # yyyy-MM-dd HH:mm:ss（缺省已固化为校验时刻）
    transfer_type: int
    page_size: int
    page_after: str    # 透明游标，原样透传


def validate_search_transfer(args) -> SearchTransferArgs:
    """校验 search-transfer 入参；不符抛 ``CliValidationError``（USAGE 回执）。"""
    raw_type = str(getattr(args, 'transfer_type', '') or '').strip()
    if not raw_type:
        raise CliValidationError(
            f'参数错误：--transfer-type 必填（{TRANSFER_TYPE_HINT}）'
        )
    if ',' in raw_type or '，' in raw_type:
        raise CliValidationError(
            f'参数错误：--transfer-type 仅支持单值（{TRANSFER_TYPE_HINT}）；'
            '查全部转存请按类型分次查询'
        )
    if raw_type not in ('5', '6', '7'):
        raise CliValidationError(
            f'参数错误：--transfer-type 只支持 {TRANSFER_TYPE_HINT}，'
            f'收到 {raw_type!r}'
        )

    start_raw = str(getattr(args, 'start_at', '') or '').strip()
    if not start_raw:
        raise CliValidationError(
            '参数错误：--start-at 必填（绝对时间；「最近」请换算为绝对起点后传入）'
        )
    start_14 = parse_time_14(start_raw)
    end_raw = str(getattr(args, 'end_at', '') or '').strip()
    # end=True：日期简写补当天 23:59:59（含当天全天，对齐 search 口径；
    # 完整时刻原样、不填走 _now_14 ——「到 X 号」直觉是含当天的）
    end_14 = parse_time_14(end_raw, end=True) if end_raw else _now_14()
    end_14 = _enforce_time_ceiling(start_14, end_14, start_raw, end_raw)
    if start_14 >= end_14:
        raise CliValidationError(
            '参数错误：--start-at 须早于 --end-at'
            f'（{format_datetime19(start_14)} ~ {format_datetime19(end_14)}）'
        )

    page_size_raw = str(getattr(args, 'page_size', '') or '').strip() or str(DEFAULT_PAGE_SIZE)
    if not page_size_raw.isdigit():
        raise CliValidationError(
            f'参数错误：--page-size 须为正整数（1-{PAGE_SIZE_MAX}），'
            f'收到 {page_size_raw!r}'
        )
    page_size = int(page_size_raw)
    if not 1 <= page_size <= PAGE_SIZE_MAX:
        raise CliValidationError(
            f'参数错误：--page-size 须在 1-{PAGE_SIZE_MAX}，收到 {page_size}'
        )

    return SearchTransferArgs(
        keyword=str(getattr(args, 'keyword', '') or '').strip(),
        start_at=format_datetime19(start_14),
        end_at=format_datetime19(end_14),
        transfer_type=int(raw_type),
        page_size=page_size,
        page_after=str(getattr(args, 'page_after', '') or '').strip(),
    )
