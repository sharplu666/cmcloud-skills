#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：share-save —— 把 139 分享链接中的文件转存到自己云盘（写操作，须用户确认）。"""
from __future__ import annotations

from typing import Optional

from cli.cli_runtime import (
    EXIT_INPUT_ERROR,
    exit_with_error,
    resolve_current_session,
)

from services.share_save.runner import run_share_save


def run(
    share_text: str,
    passwd: Optional[str] = None,
    target_dir: Optional[str] = None,
    *,
    session: Optional[str] = None,
) -> int:
    # session CLI 参数仅兼容保留，实际一律读 MCLAW_CURRENT_SESSION
    _ = session
    if not (share_text or '').strip():
        exit_with_error('转存失败：请提供 139 分享链接或分享 ID', code=EXIT_INPUT_ERROR)
    env_session = resolve_current_session(required=True)
    return run_share_save(share_text, passwd, target_dir, env_session)
