#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：upload"""
from __future__ import annotations

from cli.cli_runtime import (
    Any,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
    Optional,
    api_file_complete,
    api_file_create,
    classify_upload_parent_path,
    collect_deduped_file_path_entries,
    datetime,
    emit_file_list_card,
    emit_file_path_list_card,
    emit_jsonl,
    emit_write_file_record,
    ensure_default_session_upload_parent,
    exit_with_error,
    get_enriched_files_by_ids,
    get_file_path_map,
    os,
    requests,
    resolve_current_session,
    sha256_file,
    snapshot_trace_id,
    timezone,
)


def _resolve_upload_parent(
    target_dir: Optional[str], *, env_session: str
) -> tuple[str, str, str]:
    """解析上传目标目录，返回 (parent_file_id, parent_path, target_kind)。

    target_dir 可为云盘路径（如 /LinuxDo、/AI空间/MClaw空间/资料）或目录 fileId；
    为空时回退到当前会话默认保存目录。路径不存在时逐级创建。
    """
    target = (target_dir or '').strip()
    if not target:
        parent_file_id, parent_path = ensure_default_session_upload_parent(
            env_session, error_cls=RuntimeError
        )
        return (
            parent_file_id,
            parent_path,
            classify_upload_parent_path(parent_path, session=env_session),
        )
    if target.startswith('/'):
        from mclaw.shared.cm_cloud.folder_ops import ensure_folder_path_parts
        from mclaw.shared.postprocess.paths import (
            join_cloud_dir_path,
            split_cloud_dir_path,
        )

        parts = split_cloud_dir_path(target)
        if not parts:
            # 目标即根目录
            return '/', '/', '已上传到指定路径'
        folder = ensure_folder_path_parts(parts, error_cls=RuntimeError)
        parent_file_id = str(folder.get('fileId') or '').strip()
        if not parent_file_id:
            exit_with_error(
                f'上传失败：目标目录 {target} 未返回 fileId', code=EXIT_INPUT_ERROR
            )
        return parent_file_id, join_cloud_dir_path(parts), '已上传到指定路径'
    path_map = get_file_path_map([target], action='上传文件') or {}
    parent_path = str(path_map.get(target) or '').strip()
    if not parent_path:
        exit_with_error(
            f'上传失败：目标目录 fileId 不存在：{target}', code=EXIT_INPUT_ERROR
        )
    return target, parent_path, '已上传到指定路径'


def run(
    file_path: str,
    target_dir: Optional[str] = None,
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
        parent_file_id, parent_path, target_kind = _resolve_upload_parent(
            target_dir, env_session=env_session
        )
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

    try:
        enriched = get_enriched_files_by_ids([fid])
        if not enriched:
            exit_with_error(f'上传失败，获取文件信息失败（文件ID: {fid}）')
        path_entries = collect_deduped_file_path_entries(enriched)
        payload = {
            'record': 'meta',
            'status': 'success',
            'command': 'upload',
            'message': '上传成功',
            'parentPath': parent_path,
            'parentFileId': parent_file_id,
            'targetKind': target_kind,
        }
        if path_entries:
            payload['filePathList'] = path_entries
        emit_jsonl(payload)
        file_rows: list[dict[str, Any]] = []
        for idx, row in enumerate(enriched, start=1):
            row['actionType'] = 'upload'
            file_rows.append(emit_write_file_record(row, index=idx))
        emit_file_list_card(file_rows, total=len(file_rows), search=False, cli='upload')
        if path_entries:
            emit_file_path_list_card(path_entries, cli='upload')
    except RuntimeError as e:
        exit_with_error(str(e))
    except Exception as e:
        exit_with_error(f'上传失败: {e}', code=EXIT_INTERNAL_ERROR)

    return EXIT_OK
