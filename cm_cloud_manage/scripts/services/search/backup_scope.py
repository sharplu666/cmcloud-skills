#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备份口径目录预设：把固定的 8 个备份来源目录名解析为根目录 ``/`` 下的 fileId。

非独立检索模型——检索本身仍走 merge/file ``File``（或 merge/image ``ImageFile``），
本模块只负责「名→fileId」这一前置编排，把解析出的 id 填进
``searchFileParam.includeFileIdList`` 作为目录范围预设（cli_design.md §10）。

解析用公共库 ``mclaw.shared.cm_cloud.folder_ops.check_exists``（``batchCheckExists``
端点）：逐个查根目录 ``/`` 下是否存在同名一级目录，收 ``appFileId`` 且 ``fileType``
为 folder 的。不引用任何旧技能的客户端封装（CLAUDE.md 硬规则 1）。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from mclaw.shared.cm_cloud.folder_ops import check_exists

from services.search.args import BACKUP_SCOPE_ROOT_FOLDER_NAMES, is_valid_backup_folder_name
from services.search.errors import SearchServiceError

#: 根目录 fileId（备份口径目录均位于根目录下）
_ROOT_PARENT_FILE_ID = '/'


def resolve_backup_scope_include_ids(
    selected_names: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    """把备份口径目录名解析为根目录 ``/`` 下的 fileId。

    selected_names 为 None 或空 → 解析全部 8 个口径目录（``--backup-folder`` 不传）。
    调用方应已做白名单校验（services/search/args）；此处对非法名仅跳过不抛（防御性，非主路径）。
    返回 ``(include_file_id_list, resolved_names)``——已成功解析到 fileId 的目录名列表。

    解析失败的目录（不存在 / 非文件夹 / 未返回 fileId）被跳过；全部失败时抛
    ``SearchServiceError``（自然语言回执，属环境/服务端问题，非入参错误）。
    """
    names = _normalize_selected_names(selected_names)

    ids: List[str] = []
    resolved: List[str] = []
    for name in names:
        try:
            data = check_exists(_ROOT_PARENT_FILE_ID, name)
        except RuntimeError:
            # 单个目录解析失败不阻断其余目录（部分失败用已成功的继续检索）
            continue
        if not data.get('exist'):
            continue
        fid = str(data.get('appFileId') or '').strip()
        ftype = str(data.get('fileType') or '').strip().lower()
        if not fid:
            continue
        if ftype and ftype != 'folder':
            continue
        ids.append(fid)
        resolved.append(name)

    if not ids:
        scope_hint = '、'.join(names)
        raise SearchServiceError(
            '服务端错误：未能解析到任何可用的备份来源目录（本次范围：'
            f'{scope_hint}）。请确认账号根目录下是否存在对应备份目录，'
            '或交用户决策。'
        )
    return ids, resolved


def _normalize_selected_names(selected_names: Optional[List[str]]) -> List[str]:
    """规范化传入的口径名列表：None/空 → 全部；去重保序；剔非法名（防御性）。"""
    if not selected_names:
        return list(BACKUP_SCOPE_ROOT_FOLDER_NAMES)
    seen: set = set()
    out: List[str] = []
    for nm in selected_names:
        name = str(nm or '').strip()
        if not name or name in seen or not is_valid_backup_folder_name(name):
            continue
        seen.add(name)
        out.append(name)
    return out or list(BACKUP_SCOPE_ROOT_FOLDER_NAMES)


__all__ = ['resolve_backup_scope_include_ids']
