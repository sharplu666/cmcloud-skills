#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：get_default_save_dir（只查询不创建）"""
from __future__ import annotations

from cli.cli_runtime import (
    EXIT_INPUT_ERROR,
    EXIT_OK,
    MclawEnvError,
    emit_jsonl,
    exit_with_error,
    normalize_cli_session_id,
    query_default_session_folder,
    resolve_current_session,
)

def run(session: str = '') -> int:
    # 位置参数 session 仅兼容保留，实际一律读 MCLAW_CURRENT_SESSION
    _ = session
    try:
        env_session = resolve_current_session(required=True)
        default_folder_file_id, default_dir = query_default_session_folder(
            env_session, error_cls=RuntimeError
        )
    except MclawEnvError as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR)
    except RuntimeError as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR, from_api=True)

    emit_jsonl({
        'record': 'meta',
        'status': 'success',
        'command': 'get_default_save_dir',
        'session': normalize_cli_session_id(env_session),
        'defaultFolderPath': default_dir,
        'defaultFolderFileId': default_folder_file_id,  # 只查询不创建时为空串
        'created': False,
        'message': '查询默认保存目录成功（未创建目录）',
    })
    return EXIT_OK
