#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：share-download —— 把 139 分享链接中的文件转存到自己云盘再下载到本地（写操作，须用户确认）。"""
from __future__ import annotations

from typing import Optional

from cli.cli_runtime import (
    EXIT_INPUT_ERROR,
    exit_with_error,
    os,
    resolve_current_session,
)

from services.share_save.runner import run_share_download


def run(
    share_text: str,
    download_dir: str,
    passwd: Optional[str] = None,
    target_dir: Optional[str] = None,
    *,
    session: Optional[str] = None,
) -> int:
    # session CLI 参数仅兼容保留，实际一律读 MCLAW_CURRENT_SESSION
    _ = session
    if not (share_text or '').strip():
        exit_with_error('下载失败：请提供 139 分享链接或分享 ID', code=EXIT_INPUT_ERROR)
    if not (download_dir or '').strip():
        exit_with_error('下载失败：请提供本地保存目录', code=EXIT_INPUT_ERROR)
    if not os.path.isdir(download_dir):
        exit_with_error(f'下载失败，目录 {download_dir} 不存在', code=EXIT_INPUT_ERROR)
    env_session = resolve_current_session(required=True)
    return run_share_download(share_text, passwd, target_dir, download_dir, env_session)
