#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量 fileId → 文件详情 / 路径映射（Service 编排）。

``get_file_path_map`` / ``get_file_info_map`` 均委托 ``mclaw.shared.cm_cloud.folder_ops``。
"""

from __future__ import annotations

from typing import Any

from mclaw.shared.cm_cloud.folder_ops import (
    get_file_info_map as _shared_get_file_info_map,
    get_file_path_map as _shared_get_file_path_map,
)
from utils.helpers import CloudManageError


def get_file_info_map(
    file_ids: list[str],
    *,
    error_cls: type[Exception] = CloudManageError,
) -> dict[str, dict[str, Any]]:
    return _shared_get_file_info_map(file_ids, error_cls=error_cls)


def get_file_path_map(
    file_ids: list[str],
    *,
    error_cls: type[Exception] = CloudManageError,
) -> dict[str, str]:
    """批量 fileId → 规范化 namePath（共用实现）。"""
    return _shared_get_file_path_map(file_ids, error_cls=error_cls)
