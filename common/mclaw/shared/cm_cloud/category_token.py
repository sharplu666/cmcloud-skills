#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨 skill 共用的 category → render 英文 token。"""

from __future__ import annotations

from typing import Any


def category_render_token(raw: Any) -> str:
    """接口或中间层 category -> 卡片渲染使用的英文 category。"""
    s = str(raw or '').strip().lower()
    if s in ('doc', 'document', '文档', '4'):
        return 'doc'
    if s in ('image', '图片', 'img', '1'):
        return 'image'
    if s in ('audio', '音频', '2'):
        return 'audio'
    if s in ('video', '视频', '3'):
        return 'video'
    if s in ('folder', '文件夹', '5'):
        return 'folder'
    return 'others'


__all__ = ['category_render_token']
