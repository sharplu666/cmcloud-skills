#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索与 batchGet 响应规范化（纯函数）。

将 merge/file、batchGet、checkExists 等接口返回的行结构统一为 CLI 内部字段。

用法::

    from mclaw.shared.postprocess.merge_normalize import (
        is_result_row_successful,
        merge_file_row_normalize,
        normalize_check_exists_data,
        parse_batch_get_src_file,
        split_result_rows,
    )

    files = [merge_file_row_normalize(row) for row in raw_file_list]
    ok, failed = split_result_rows(batch_rows)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from mclaw.shared.cm_cloud.transforms import (
    cloud_asset_time_to_skill14,
    normalize_search_category,
)


def is_result_row_successful(row: dict[str, Any]) -> bool:
    """``errCode`` 缺省或为 ``'0000'`` 视为成功。"""
    return str(row.get('errCode') or '0000') == '0000'


def split_result_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 :func:`is_result_row_successful` 拆成 (成功行, 失败行)。"""
    ok_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    for row in rows:
        if is_result_row_successful(row):
            ok_rows.append(row)
        else:
            failed_rows.append(row)
    return ok_rows, failed_rows


def merge_file_row_normalize(row: Dict[str, Any]) -> Dict[str, Any]:
    """将 merge 搜索 File 响应规范化为 CLI 内部统一结构。"""
    ext = str(row.get('fileExtension') or row.get('extension') or '')
    cat_tok = normalize_search_category(str(row.get('category') or ''))

    type_raw = str(row.get('type') or '').strip().lower()
    type_val = {'file': '1', 'folder': '2'}.get(type_raw, type_raw)

    media = row.get('mediaMetaInfo')
    if isinstance(media, dict):
        media_out = dict(media)
        dur_raw = media.get('duration')
        if dur_raw is not None:
            try:
                media_out['duration'] = int(float(str(dur_raw)))
            except (ValueError, TypeError):
                media_out['duration'] = 0
        taken_raw = media_out.get('takenAt')
        if taken_raw is not None and str(taken_raw).strip():
            media_out['takenAt'] = cloud_asset_time_to_skill14(taken_raw)
    else:
        media_out = {'duration': 0}

    out: Dict[str, Any] = {
        'fileId': row.get('fileId', ''),
        'name': row.get('name', ''),
        'parentFileId': row.get('parentFileId', ''),
        'namePath': str(row.get('namePath') or ''),
        'type': type_val,
        'fileExtension': ext,
        'extension': ext,
        'category': cat_tok,
        'createdAt': cloud_asset_time_to_skill14(row.get('createdAt')),
        'updatedAt': cloud_asset_time_to_skill14(row.get('updatedAt')),
        'size': int(row.get('size') or 0),
        'contentHash': str(row.get('contentHash') or ''),
        'contentHashAlgorithm': str(row.get('contentHashAlgorithm') or ''),
        'mediaMetaInfo': media_out,
        'addressDetail': row.get('addressDetail') or {},
    }
    info = row.get('aiAnalysisInfo')
    if isinstance(info, dict):
        out['aiAnalysisInfo'] = info
    return out


def parse_batch_get_src_file(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 batchFileResults 单条解析 srcFile；兼容顶层 fileId。"""
    if not isinstance(item, dict):
        return None
    src = item.get('srcFile')
    src = dict(src) if isinstance(src, dict) else {}
    file_id = str(src.get('fileId') or item.get('fileId') or '').strip()
    if not file_id:
        return None
    src['fileId'] = file_id
    return src


def normalize_check_exists_data(raw: Any) -> Dict[str, Any]:
    """将 checkExists 的 data 统一为 exist / appFileId / fileType。"""
    data = raw if isinstance(raw, dict) else {}
    return {
        'exist': bool(data.get('exist')),
        'appFileId': str(data.get('fileId') or data.get('appFileId') or '').strip(),
        'fileType': str(data.get('type') or data.get('fileType') or '').strip().lower(),
    }


__all__ = [
    'is_result_row_successful',
    'split_result_rows',
    'merge_file_row_normalize',
    'parse_batch_get_src_file',
    'normalize_check_exists_data',
]
