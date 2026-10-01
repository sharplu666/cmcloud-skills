#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云 ``ApiDispatcher`` 进程内单例（host + cloud_auth）。

organize / common 编排共用同一实例，避免多模块各自持有一份 dispatcher。

用法::

    from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher

    response = get_cloud_dispatcher().some_api(...)
"""

from __future__ import annotations

from typing import Optional

from mclaw.api import ApiDispatcher
from mclaw.shared.cm_cloud.cloud_auth import get_cloud_auth_headers, get_cloud_host

_dispatcher_singleton: Optional[ApiDispatcher] = None


def get_cloud_dispatcher() -> ApiDispatcher:
    """返回进程内唯一的个人云 ``ApiDispatcher``。"""
    global _dispatcher_singleton
    if _dispatcher_singleton is None:
        _dispatcher_singleton = ApiDispatcher(
            host=get_cloud_host(),
            auth_fn=get_cloud_auth_headers,
        )
    return _dispatcher_singleton


def reset_cloud_dispatcher_for_tests() -> None:
    """测试用：清空单例，便于注入假 host / auth。"""
    global _dispatcher_singleton
    _dispatcher_singleton = None


__all__ = ['get_cloud_dispatcher', 'reset_cloud_dispatcher_for_tests']
