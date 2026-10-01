#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：create_default_save_dir"""
from __future__ import annotations

from cli.cli_runtime import (
    EXIT_INPUT_ERROR,
    EXIT_OK,
    MclawEnvError,
    emit_jsonl,
    ensure_default_session_upload_parent,
    exit_with_error,
    normalize_cli_session_id,
    resolve_current_session,
)

def run(session: str = '') -> int:
    # 位置参数 session 仅兼容保留，实际一律读 MCLAW_CURRENT_SESSION
    _ = session
    try:
        env_session = resolve_current_session(required=True)
        default_folder_file_id, default_dir = ensure_default_session_upload_parent(
            env_session, error_cls=RuntimeError
        )
    except MclawEnvError as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR)
    except RuntimeError as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR, from_api=True)

    emit_jsonl({
        'record': 'meta',
        'status': 'success',
        'command': 'create_default_save_dir',
        'session': normalize_cli_session_id(env_session),
        'defaultFolderPath': default_dir,
        'defaultFolderFileId': default_folder_file_id,
        'message': '创建默认保存目录成功',
    })
    return EXIT_OK
