#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索后端降级提示：识别已知已下线的服务端点，返回可行动的替代方案。

背景（2026-10 实测）：
- ai.yun.139.com 的 intelligent/search 系列接口返回 404 Route Not Found，
  影响 search / semantic-search / dynamic / person-search / search-by-ids；
- huidu-middle.yun.139.com 的转存查询接口不可达（连接超时/被重置），
  影响 search-transfer。
文件原子操作（上传/下载/查详情/判存在/复制/移动/重命名/建目录）走
personal-kd-njs 网关，不受影响。
"""
from __future__ import annotations

from typing import Optional

_AI_SEARCH_HINT = (
    '139 AI 搜索服务已下线（接口返回 404 Route Not Found），'
    '关键词/语义/动态/人物搜索暂不可用。替代方案：'
    '① 已知目录+文件名，用 batch_check_exists <父目录ID>:<文件名> 定位；'
    '② 有分享链接，用 share-save / share-download 转存下载；'
    '③ 已知 fileId，用 batch_get 查详情 / download 下载。'
)

_TRANSFER_SEARCH_HINT = (
    '139 转存查询服务不可达（huidu-middle.yun.139.com 连接失败），'
    '按转存来源查询暂不可用。替代方案：'
    '有分享链接时直接用 share-save / share-download 转存下载。'
)


def describe_backend_error(exc: BaseException) -> Optional[str]:
    """识别已知下线后端，返回面向用户的可行动文案；未知错误返回 None。"""
    text = str(exc or '')
    if '404 Route Not Found' in text and 'ai.yun.139.com' in text:
        return _AI_SEARCH_HINT
    if 'intelligent/search' in text and ('404' in text or 'Route Not Found' in text):
        return _AI_SEARCH_HINT
    if 'huidu-middle.yun.139.com' in text:
        return _TRANSFER_SEARCH_HINT
    return None
