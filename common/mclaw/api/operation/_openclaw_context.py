#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""openclaw 接口公共上下文（实例标识等）。"""

from __future__ import annotations

import os

__all__ = ['resolve_openclaw_id']


def resolve_openclaw_id(explicit: str | None = None) -> str:
    """解析 ``openclawId``：显式入参优先，否则读 ``OPENCLAW_ID`` 环境变量。"""
    value = (explicit or os.getenv('OPENCLAW_ID') or '').strip()
    if not value:
        raise ValueError(
            '未配置 OPENCLAW_ID 环境变量，无法调用 openclaw 接口。'
        )
    return value
