#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预搜索拉全量 API 分页常量（manage / organize 共用，与 organize Step 2 对齐）。"""

from __future__ import annotations

from typing import List, Optional

# merge/image, searchType=SemanticImage
PRESEARCH_IMAGE_PAGE_SIZE: int = 2000
# merge/image, searchType=ImageFile（manage 仅图片 -t 1 走此路由）
PRESEARCH_IMAGE_FILE_PAGE_SIZE: int = 1000
# merge/image, searchType=ImageDynamic
PRESEARCH_IMAGE_DYNAMIC_PAGE_SIZE: int = 200
# merge/file, searchType=File
PRESEARCH_FILE_PAGE_SIZE: int = 1000
# merge/file, searchType=FileDynamic
PRESEARCH_FILE_DYNAMIC_PAGE_SIZE: int = 200
# CLI --page-size 允许的最大值
MAX_PAGE_SIZE: int = 5000


def is_image_only_file_types(file_types: Optional[List[int]]) -> bool:
    return bool(file_types and len(file_types) == 1 and file_types[0] == 1)


def resolve_fetch_all_page_size(*, file_types: Optional[List[int]] = None) -> int:
    """拉全量翻页时的 API pageSize（与 SearchManager 预搜索默认一致）。

    manage ``search_keyword`` / ``search_filter`` 在聚类或 ``--top`` 模式下使用；
    与 CLI ``--page-size``（默认 20，仅影响普通分页展示）无关。
    """
    if is_image_only_file_types(file_types):
        return PRESEARCH_IMAGE_FILE_PAGE_SIZE
    return PRESEARCH_FILE_PAGE_SIZE


def resolve_semantic_image_fetch_all_page_size() -> int:
    """语义搜图（merge/image SemanticImage）拉全量时的 API pageSize。"""
    return PRESEARCH_IMAGE_PAGE_SIZE
