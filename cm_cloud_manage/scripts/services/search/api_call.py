#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge 搜索的真实调用点（search 子包唯一的网络出入口）。

dispatcher / 重试 / 超时 / 脱敏全部由公共库承担；tmp-test 用 fake 实现替换
本模块的 ``call_merge_search``，不触碰网络层。
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from mclaw.api.search_fusion.search_merge_file_api import (
    MergeFileSearchParam,
    MergeFileSearchRequest,
    MergeFileSearchResponse,
)
from mclaw.api.search_fusion.search_merge_image_api import (
    MergeImageSearchParam,
    MergeImageSearchRequest,
    MergeImageSearchResponse,
)
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher

from services.search.param_build import SearchTask, search_param_payload

MergeSearchResponse = Union[MergeImageSearchResponse, MergeFileSearchResponse]


def call_merge_search(
    task: SearchTask,
    page_after: Optional[List[Any]],
    semantic_info: Optional[str] = None,
) -> MergeSearchResponse:
    """按任务与当前页游标发起一次 merge 搜索，返回公共库 Response。

    ``page_after`` 原样回传上一页响应的 pageAfter（首页为 None）。
    ``semantic_info`` 语义搜图翻页回传的冻结首页值（首页请求不传）。
    网络/超时错误由公共库抛 RuntimeError；业务失败（success=False）由调用方判定。
    """
    payload = search_param_payload(task, page_after, semantic_info)
    dispatcher = get_cloud_dispatcher()
    if task.api == 'merge_image':
        request = MergeImageSearchRequest(
            search_param=MergeImageSearchParam.model_validate(payload)
        )
        return dispatcher.search_fusion.search_merge_image(request)
    request = MergeFileSearchRequest(
        search_param=MergeFileSearchParam.model_validate(payload)
    )
    return dispatcher.search_fusion.search_merge_file(request)


__all__ = ['call_merge_search']
