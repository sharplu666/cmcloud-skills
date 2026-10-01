#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云搜索 Service —— 条件构建、整合搜索、分页游标。"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

_SCRIPTS_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..')
)
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from cli_trace import set_primary_api_context  # noqa: E402

from mclaw.api import ApiDispatcher
from mclaw.api.search_fusion.search_merge_file_api import (
    MergeFileSearchParam,
    MergeFileSearchRequest,
)
from mclaw.api.search_fusion.search_merge_image_api import (
    MergeImageSearchParam,
    MergeImageSearchRequest,
)
from mclaw.shared.postprocess.search_param import (
    build_search_file_param_v3,
    normalize_page_after_input,
    page_after_to_cli_cursor,
)

from utils.config import (
    MERGE_SEARCH_PAGE_SIZE,
)
from mclaw.shared.postprocess.merge_normalize import merge_file_row_normalize
from mclaw.shared.postprocess.api_obs import data_dict, err_message, finish

__all__ = [
    'build_search_file_param_v3',
    'normalize_page_after_input',
    'page_after_to_cli_cursor',
    'search_merge_file',
    'search_merge_image',
]


def _build_page_info(
    page_size: int,
    page_after: Optional[Any],
    sort_infos: Optional[List[Dict[str, Any]]],
    need_total_count: int,
) -> Dict[str, Any]:
    page_info: Dict[str, Any] = {'pageSize': page_size, 'needTotalCount': need_total_count}
    pa = normalize_page_after_input(page_after)
    if pa is not None:
        page_info['pageAfter'] = pa
    if sort_infos:
        page_info['sortInfos'] = sort_infos
    return page_info


def _unpack_search(response: Any) -> Tuple[List[Dict[str, Any]], int, Any, str]:
    data = data_dict(response)
    files = [merge_file_row_normalize(f) for f in (data.get('fileList') or []) if isinstance(f, dict)]
    # semanticInfo：语义搜图（SemanticImage）首页返回的语义理解信息；其他场景为空串
    semantic_info = str(data.get('semanticInfo') or '')
    return files, int(data.get('totalCount') or 0), data.get('pageAfter') or '', semantic_info


def search_merge_file(
    dispatcher: ApiDispatcher,
    search_file_param: Dict[str, Any],
    *,
    page_size: int = MERGE_SEARCH_PAGE_SIZE,
    page_after: Optional[Any] = None,
    sort_infos: Optional[List[Dict[str, Any]]] = None,
    need_total_count: int = 1,
) -> Tuple[List[Dict[str, Any]], int, Any, str]:
    """个人云文件类整合搜索（searchType=File）。返回 (files, total_count, page_after, semantic_info)。"""
    param = MergeFileSearchParam.model_validate({
        'searchType': 'File',
        'searchFileParam': search_file_param,
        'pageInfo': _build_page_info(page_size, page_after, sort_infos, need_total_count),
    })
    request = MergeFileSearchRequest(search_param=param)
    set_primary_api_context('File', request.to_payload())

    started = time.perf_counter()
    response = dispatcher.search_fusion.search_merge_file(request)
    finish('richlifeApp/aiService/api/text/intelligent/search/merge/file', started, response)
    if not response.success:
        raise RuntimeError(f'搜索失败: {err_message(response, "业务失败")}')
    return _unpack_search(response)


def search_merge_image(
    dispatcher: ApiDispatcher,
    *,
    search_type: str = 'SemanticImage',
    search_image_param: Optional[Dict[str, Any]] = None,
    search_file_param: Optional[Dict[str, Any]] = None,
    page_size: int = MERGE_SEARCH_PAGE_SIZE,
    page_after: Optional[Any] = None,
    sort_infos: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], int, Any, str]:
    """个人云图片类整合搜索（SemanticImage / ImageFile）。返回 (files, total_count, page_after, semantic_info)。"""
    sp: Dict[str, Any] = {
        'searchType': search_type,
        'pageInfo': _build_page_info(page_size, page_after, sort_infos, need_total_count=1),
    }
    if search_image_param:
        sp['searchImageParam'] = search_image_param
    if search_file_param:
        sp['searchFileParam'] = search_file_param

    request = MergeImageSearchRequest(search_param=MergeImageSearchParam.model_validate(sp))
    set_primary_api_context(search_type, request.to_payload())

    started = time.perf_counter()
    response = dispatcher.search_fusion.search_merge_image(request)
    finish('richlifeApp/aiService/api/text/intelligent/search/merge/image', started, response)
    if not response.success:
        raise RuntimeError(f'搜索失败: {err_message(response, "业务失败")}')
    return _unpack_search(response)
