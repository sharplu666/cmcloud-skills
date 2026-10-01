#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目录创建与 MClaw 空间路径解析（Service 编排）。

``ensure_mclaw_dir_path`` 委托 ``mclaw.shared.cm_cloud.folder_ops``；
``classify_upload_parent_path`` 为 upload 路径分类（manage CLI 专用）。
"""

from __future__ import annotations

from typing import Any, Optional

from utils.config import (
    AI_SPACE_DIR_NAME,
    APP_NAME,
    CHAT_FILE_DIR_NAME,
)
from mclaw.shared.postprocess.paths import (
    compact_segment_name,
    split_cloud_dir_path,
)
from mclaw.shared.cm_cloud.session_cli_validate import normalize_cli_session_id
from utils.helpers import CloudManageError


def classify_upload_parent_path(parent_path: str, session: Optional[str] = None) -> str:
    parts = split_cloud_dir_path(parent_path)
    if len(parts) < 4:
        return '已上传到指定路径'
    if (
        compact_segment_name(parts[0]) != compact_segment_name(AI_SPACE_DIR_NAME)
        or compact_segment_name(parts[1]) != compact_segment_name(APP_NAME)
        or compact_segment_name(parts[2]) != compact_segment_name(CHAT_FILE_DIR_NAME)
    ):
        return '已上传到指定路径'
    if session:
        normalized_session_id = normalize_cli_session_id(str(session).strip())
        if normalized_session_id and compact_segment_name(parts[3]) == compact_segment_name(
            normalized_session_id
        ):
            return '已上传到默认路径'
        return '已上传到其他会话默认路径'
    return '已上传到其他会话默认路径'


def ensure_mclaw_dir_path(
    dir_path: str,
    *,
    error_cls: type[Exception] = CloudManageError,
) -> dict[str, Any]:
    """确保 MClaw 下完整路径（含各级）存在，返回末级目录信息。

    目录创建走 ``mclaw.shared.cm_cloud.folder_ops``。
    """
    from mclaw.shared.cm_cloud.folder_ops import ensure_mclaw_dir_path as _ensure

    return _ensure(dir_path, error_cls=error_cls)
