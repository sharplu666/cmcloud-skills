#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：mkdir"""
from __future__ import annotations

from cli.cli_runtime import (
    Any,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    emit_jsonl,
    exit_with_error,
    get_single_file_path,
    snapshot_trace_id,
)
from mclaw.shared.cm_cloud.folder_ops import ensure_folder_path_parts
from mclaw.shared.postprocess.paths import join_cloud_dir_path, split_cloud_dir_path

def _mkdir_result_message(
    segment_actions: list[str],
    *,
    requested_path: str,
    resolved_path: str,
) -> tuple[str, str]:
    """返回 (message, mkdirAction)：created | reused | mixed。"""
    created_count = sum(1 for a in segment_actions if a == 'created')
    reused_count = len(segment_actions) - created_count
    path_note = ''
    if requested_path != resolved_path:
        path_note = (
            f'输入路径为 {requested_path!r}，已复用云盘已有目录 {resolved_path!r} '
            f'（同级存在去空格同名文件夹，未新建带空格目录）'
        )

    if created_count == 0:
        message = '目录已存在，已复用，未新建'
        action = 'reused'
    elif reused_count == 0:
        message = '创建文件夹成功'
        action = 'created'
    else:
        message = f'部分目录已存在已复用（{reused_count} 级），新建 {created_count} 级'
        action = 'mixed'

    if path_note:
        message = f'{message}。{path_note}'
    return message, action

def run(dir_path: str) -> int:
    raw_path = str(dir_path or '').strip()
    if not raw_path:
        exit_with_error('创建文件夹失败：须传入完整云盘目录路径', code=EXIT_INPUT_ERROR)
    try:
        parts = split_cloud_dir_path(raw_path)
        requested_path = join_cloud_dir_path(parts)
        folder = ensure_folder_path_parts(parts, error_cls=RuntimeError)
        segment_actions = list(folder.pop('_segmentActions', []) or [])
        created_file_id = str(folder.get('fileId') or '').strip()
        if not created_file_id:
            raise RuntimeError(f'创建文件夹失败：目录 {raw_path} 未返回 fileId')
        created_path = get_single_file_path(created_file_id, action='创建文件夹')
        if not created_path:
            created_path = requested_path
        message, mkdir_action = _mkdir_result_message(
            segment_actions,
            requested_path=requested_path,
            resolved_path=created_path,
        )
    except RuntimeError as e:
        exit_with_error(str(e))

    snapshot_trace_id()

    meta: dict[str, Any] = {
        'record': 'meta',
        'status': 'success',
        'command': 'mkdir',
        'message': message,
        'mkdirAction': mkdir_action,
        'fileId': created_file_id,
        'filePath': created_path,
    }
    if requested_path != created_path:
        meta['requestedPath'] = requested_path
    emit_jsonl(meta)
    return EXIT_OK
