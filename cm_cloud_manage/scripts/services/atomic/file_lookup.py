#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件/目录查询与 AI 空间判定。"""
from __future__ import annotations

from typing import Any

from utils.config import MCLAW_ALLOWED_DIR
from services.atomic.client import (
    api_batch_get,
    api_batch_get_path,
    parse_batch_get_src_file,
)
from mclaw.shared.postprocess.paths import normalize_cloud_dir_path, normalize_name_path

def is_under_ai_space(fileid: str) -> bool:
    """判断文件是否在 AI空间下。"""
    return batch_is_under_ai_space([fileid]).get(str(fileid or '').strip(), False)

def batch_is_under_ai_space(file_ids: list[str]) -> dict[str, bool]:
    """批量判断文件是否在 AI空间下。"""
    normalized_ids = [str(fid or '').strip() for fid in file_ids if str(fid or '').strip()]
    if not normalized_ids:
        return {}

    status_map = {fid: False for fid in normalized_ids}
    for i in range(0, len(normalized_ids), 100):
        chunk = normalized_ids[i:i + 100]
        path_results = api_batch_get_path(chunk)
        if not isinstance(path_results, list):
            raise RuntimeError(f'判断文件是否在 AI空间下失败：batchGetPath 返回结果格式不正确，期望 list，实际为 {type(path_results).__name__}')

        for row in path_results:
            if not isinstance(row, dict):
                raise RuntimeError(f'判断文件是否在 AI空间下失败：batchGetPath 返回条目格式不正确，期望 dict，实际为 {type(row).__name__}')

            fid = str(row.get('fileId') or '').strip()
            if not fid:
                continue
            if str(row.get('errCode') or '0000') != '0000':
                status_map[fid] = False
                continue

            name_path_raw = row.get('namePath')
            if not isinstance(name_path_raw, str):
                raise RuntimeError('判断文件是否在 AI空间下失败：batchGetPath 返回结果缺少合法的 namePath')

            name_path = normalize_name_path(name_path_raw)
            status_map[fid] = name_path == MCLAW_ALLOWED_DIR or name_path.startswith(MCLAW_ALLOWED_DIR + '/')

    return status_map

def get_single_file_info(file_id: str, *, action: str) -> dict[str, Any]:
    """查询单个文件/目录详情，确保 fileId 存在且可访问。"""
    normalized_file_id = str(file_id or '').strip()
    if not normalized_file_id:
        raise RuntimeError(f'{action}失败：fileId 不能为空')

    rows = api_batch_get([normalized_file_id])
    if not rows:
        raise RuntimeError(f'{action}失败：未找到 fileId={normalized_file_id} 对应的文件或目录')

    row = rows[0]
    if str(row.get('errCode') or '') != '0000':
        raise RuntimeError(
            f'{action}失败：查询 fileId={normalized_file_id} 详情失败：{row.get("message") or row.get("errCode") or "未知错误"}'
        )

    info = parse_batch_get_src_file(row)
    if not info:
        raise RuntimeError(f'{action}失败：查询 fileId={normalized_file_id} 详情返回结果不完整')
    return info

def get_single_file_path(file_id: str, *, action: str) -> str:
    """查询单个文件/目录的权威路径。"""
    normalized_file_id = str(file_id or '').strip()
    if not normalized_file_id:
        raise RuntimeError(f'{action}失败：fileId 不能为空')

    rows = api_batch_get_path([normalized_file_id])
    if not rows:
        raise RuntimeError(f'{action}失败：未找到 fileId={normalized_file_id} 的路径信息')

    row = rows[0]
    if str(row.get('errCode') or '') != '0000':
        raise RuntimeError(
            f'{action}失败：查询 fileId={normalized_file_id} 路径失败：{row.get("message") or row.get("errCode") or "未知错误"}'
        )

    name_path = row.get('namePath')
    if not isinstance(name_path, str) or not name_path.strip():
        raise RuntimeError(f'{action}失败：查询 fileId={normalized_file_id} 路径返回结果不完整')
    return normalize_cloud_dir_path(name_path)

def get_file_path_map(file_ids: list[str], *, action: str) -> dict[str, str]:
    """批量查询 fileId 对应的权威路径。"""
    normalized_ids = list(dict.fromkeys(str(fid or '').strip() for fid in file_ids if str(fid or '').strip()))
    if not normalized_ids:
        return {}

    path_map: dict[str, str] = {}
    ids_to_query = [fid for fid in normalized_ids if fid != '/']
    if '/' in normalized_ids:
        path_map['/'] = '/'

    for i in range(0, len(ids_to_query), 100):
        chunk = ids_to_query[i:i + 100]
        rows = api_batch_get_path(chunk)
        if not isinstance(rows, list):
            raise RuntimeError(
                f'{action}失败：批量查询路径返回结果格式不正确，期望 list，实际为 {type(rows).__name__}'
            )
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError(
                    f'{action}失败：批量查询路径返回条目格式不正确，期望 dict，实际为 {type(row).__name__}'
                )
            fid = str(row.get('fileId') or '').strip()
            if not fid:
                continue
            if str(row.get('errCode') or '0000') != '0000':
                continue
            name_path = row.get('namePath') or row.get('namepath') or ''
            if not isinstance(name_path, str) or not name_path.strip():
                continue
            path_map[fid] = normalize_cloud_dir_path(name_path)

    return path_map
