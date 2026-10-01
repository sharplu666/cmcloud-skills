#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个人云鉴权与可写根路径（非后处理；归属 ``mclaw.shared.cm_cloud``）。

统一走 ``mclaw.api.auth.get_skill_auth`` / ``get_auth_header``，禁止第二套 token 逻辑。

用法::

    from mclaw.shared.cm_cloud.cloud_auth import (
        get_cloud_auth_headers,
        get_cloud_host,
        mclaw_allowed_dir,
    )

    host = get_cloud_host()
    headers = get_cloud_auth_headers()
    root = mclaw_allowed_dir()  # 如 /AI空间/MClaw空间
"""

from __future__ import annotations

from mclaw.api.auth import get_auth_header, get_skill_auth

AI_SPACE_DIR_NAME = 'AI空间'


def get_cloud_host() -> str:
    """个人云 Open API 根地址。"""
    return str(get_skill_auth().host or '').strip().rstrip('/')


def get_cloud_auth_headers() -> dict:
    """标准云盘 JSON 鉴权请求头（每次实时读 .env）。"""
    return dict(get_auth_header())


def get_cloud_app_name() -> str:
    """应用名（拼 MClaw 空间路径用）。"""
    return str(get_skill_auth().app_name or '').strip()


def mclaw_allowed_dir() -> str:
    """本技能可写根路径，如 ``/AI空间/MClaw空间``。"""
    app_name = get_cloud_app_name()
    if not app_name:
        raise ValueError('CM_CLOUD_APP_NAME 未配置，无法解析 MClaw 可写根路径')
    return f'/{AI_SPACE_DIR_NAME}/{app_name}'


__all__ = [
    'AI_SPACE_DIR_NAME',
    'get_cloud_host',
    'get_cloud_auth_headers',
    'get_cloud_app_name',
    'mclaw_allowed_dir',
]
