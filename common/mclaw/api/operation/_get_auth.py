#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""operation 子包 openclaw / photoOrganize 专用鉴权头。"""

from __future__ import annotations

from typing import Dict

from mclaw.api.album._get_auth import X_YUN_CLIENT_INFO
from mclaw.api.auth import get_auth_header

__all__ = ['get_photo_organize_header']


def get_photo_organize_header(*, multipart: bool = False) -> Dict[str, str]:
    """photoOrganize submit / query 鉴权头。

    在标准云盘鉴权头基础上追加：
      - ``x-yun-client-info``（设备指纹，与相册接口一致）

    multipart 提交时**不**设置 ``Content-Type``，由 requests 自动生成 boundary。
    """
    h = get_auth_header()
    h['x-yun-client-info'] = X_YUN_CLIENT_INFO
    if not multipart:
        h['Content-Type'] = 'application/json'
    return h
