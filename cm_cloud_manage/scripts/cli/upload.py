#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：upload"""
from __future__ import annotations

from cli.cli_runtime import (
    EXIT_INPUT_ERROR,
    EXIT_OK,
    Optional,
    api_file_complete,
    api_file_create,
    classify_upload_parent_path,
    datetime,
    emit_jsonl,
    emit_write_file_record,
    ensure_default_session_upload_parent,
    exit_with_error,
    os,
    requests,
    resolve_current_session,
    sha256_file,
    snapshot_trace_id,
    timezone,
)


def run(
    file_path: str,
    *,
    session: Optional[str] = None,
) -> int:
    # session CLI 参数仅兼容保留，实际一律读 MCLAW_CURRENT_SESSION
    _ = session

    if not os.path.exists(file_path):
        exit_with_error(f'上传失败：本地文件不存在：{file_path}', code=EXIT_INPUT_ERROR)
    if os.path.isdir(file_path):
        exit_with_error(f'上传失败，{file_path} 是一个目录，不是文件', code=EXIT_INPUT_ERROR)
    if not os.path.isfile(file_path):
        exit_with_error(f'上传失败：本地文件不存在：{file_path}', code=EXIT_INPUT_ERROR)

    try:
        env_session = resolve_current_session(required=True)
        parent_file_id, parent_path = ensure_default_session_upload_parent(
            env_session, error_cls=RuntimeError
        )
        target_kind = classify_upload_parent_path(parent_path, session=env_session)
    except (RuntimeError, ValueError) as e:
        exit_with_error(str(e), code=EXIT_INPUT_ERROR, from_api=True)

    name = os.path.basename(file_path)
    size = os.path.getsize(file_path)

    chash = sha256_file(file_path)

    try:
        uid, fid, pfid, put_url = api_file_create(
            name,
            size,
            parent_path=None,
            parent_file_id=parent_file_id,
        )
    except RuntimeError as e:
        exit_with_error(f'上传文件失败: {e}')

    headers = {
        'Host': put_url.split('/')[2],
        'Date': datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT'),
        'Content-Type': 'application/octet-stream',
    }

    with open(file_path, 'rb') as f:
        resp = requests.put(put_url, data=f, headers=headers)

    if resp.status_code != 200 or not api_file_complete(uid, fid, chash):
        exit_with_error(f'上传文件失败: {resp.status_code} {resp.text}')

    snapshot_trace_id()

    # 上传完成即视为成功：不再额外回查文件信息做确认
    payload = {
        'record': 'meta',
        'status': 'success',
        'command': 'upload',
        'message': '上传成功',
        'fileId': fid,
        'fileName': name,
        'fileSize': size,
        'parentPath': parent_path,
        'parentFileId': parent_file_id,
        'targetKind': target_kind,
    }
    emit_jsonl(payload)
    emit_write_file_record(
        {
            'fileId': fid,
            'fileName': name,
            'fileSize': size,
            'actionType': 'upload',
        },
        index=1,
        parent_file_id=parent_file_id,
    )

    return EXIT_OK
