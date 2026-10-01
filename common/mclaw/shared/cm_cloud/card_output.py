#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 卡片输出约定（loadMore 首行 searchParam 等）。"""

from __future__ import annotations

import copy
from typing import Any

# 卡片 loadMore 首行 searchParam 内展示用 pageSize 上限（与真实 API 请求 pageSize 解耦）
CARD_SEARCH_PARAM_PAGE_SIZE = 50


def display_page_size_for_card_output(page_size: Any) -> Any:
    """将 API pageSize 转为卡片展示值：>50 时 cap 为 50，否则保留原值。"""
    try:
        n = int(page_size)
    except (TypeError, ValueError):
        return page_size
    if n > CARD_SEARCH_PARAM_PAGE_SIZE:
        return CARD_SEARCH_PARAM_PAGE_SIZE
    return n


def normalize_search_param_for_card_output(search_param: Any) -> Any:
    """卡片 / 空结果 meta 输出的 searchParam：pageInfo.pageSize 展示规则见 display_page_size_for_card_output。

    仅影响 CLI stdout 展示，不改变实际 API 请求分页大小。
    """
    if not isinstance(search_param, dict):
        return search_param
    out = copy.deepcopy(search_param)
    page_info = out.get('pageInfo')
    if isinstance(page_info, dict) and 'pageSize' in page_info:
        page_info['pageSize'] = display_page_size_for_card_output(page_info['pageSize'])
    elif 'pageSize' in out:
        out['pageSize'] = display_page_size_for_card_output(out['pageSize'])
    return out


def attach_semantic_info_to_search_param(
    search_param: Any,
    semantic_info: Any,
    param_key: str = 'searchImageParam',
) -> Any:
    """把 ``semanticInfo`` 注入卡片 searchParam 的目标子参数内部。

    semanticInfo 仅首页返回：语义搜图（SemanticImage）注入 ``searchImageParam``，
    图文搜人（SemanticImagePerson）注入 ``searchImagePersonParam``（通过
    ``param_key`` 指定）；其余字段（含末位的 ``pageInfo``）不动。
    ``semantic_info`` 为空、``search_param`` 非 dict、或无目标子参数时原样返回；
    注入不修改入参。
    """
    if not semantic_info or not isinstance(search_param, dict):
        return search_param
    image_param = search_param.get(param_key)
    if not isinstance(image_param, dict):
        return search_param
    out = copy.deepcopy(search_param)
    out[param_key]['semanticInfo'] = semantic_info
    return out
