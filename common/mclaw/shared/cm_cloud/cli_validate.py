#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云盘个人云 fileId 格式校验（33 / 44 / 45 / 49 位字符串，可含 -、_ 等）。"""

from __future__ import annotations

import sys
from typing import Iterable

#: 云盘 fileId 合法长度集合。
#: 33/44/45/49 为 MClaw Open API 侧长度；通用(app)后端实测还会出现 34 位
#: （如 AI空间 下的 FvWfq-CIA71J1dmOfQspPt6fn7T6GgMhS），故并入 34。
CLOUD_FILE_ID_LENGTHS = frozenset({33, 34, 44, 45, 49})
CLOUD_FILE_ID_LENGTH = 33

_ROOT_PARENT_ALIASES = frozenset({'/', 'root'})

_REMEDIATION = (
    '请根据上下文中的 CLI 输出核对 fileId（如 search、batch_get 返回的 fileId 字段），'
    '勿使用知识库 resourceId、笔记 noteId、相册 albumId 等非云盘 fileId。'
)


class CloudFileIdValidationError(ValueError):
    """云盘 fileId 入参校验失败。"""


def _allowed_lengths_text() -> str:
    return '、'.join(str(n) for n in sorted(CLOUD_FILE_ID_LENGTHS))


def _emit_stderr_and_raise(message: str) -> None:
    print(f'错误：{message}', file=sys.stderr, flush=True)
    raise CloudFileIdValidationError(message)


def is_cloud_file_id(value: str) -> bool:
    """云盘 fileId：去首尾空白后长度须为 33 / 44 / 45 / 49（字符集不限）。"""
    return len(str(value or '').strip()) in CLOUD_FILE_ID_LENGTHS


def describe_cloud_file_id_issue(file_id: str) -> str:
    """返回空字符串表示通过；否则为可读失败原因（不抛异常、不写 stderr）。"""
    normalized = str(file_id or '').strip()
    if not normalized:
        return 'fileId 不能为空'
    lowered = normalized.lower()
    if lowered in _ROOT_PARENT_ALIASES or normalized == '/':
        return '不能使用根目录标识作为入册 fileId'
    if is_cloud_file_id(normalized):
        return ''
    return (
        f'不是合法云盘 fileId（须为 {_allowed_lengths_text()} 位字符串之一，'
        f'当前 {len(normalized)} 位）'
    )


def _format_invalid_id(value: str, *, label: str, index: int | None) -> str:
    text = str(value or '').strip()
    allowed = _allowed_lengths_text()
    if index is None:
        return (
            f'{label} 校验失败：{text!r} 不是合法云盘 fileId'
            f'（须为 {allowed} 位字符串之一，当前 {len(text)} 位）。{_REMEDIATION}'
        )
    return (
        f'{label} 第 {index} 项校验失败：{text!r} 不是合法云盘 fileId'
        f'（须为 {allowed} 位字符串之一，当前 {len(text)} 位）。{_REMEDIATION}'
    )


def validate_cloud_file_id(file_id: str, *, context: str = '') -> str:
    """校验单个云盘 fileId；根目录别名 ``/``、``root`` 原样返回 ``/``。"""
    label = context or 'fileId'
    normalized = str(file_id or '').strip()
    if not normalized:
        _emit_stderr_and_raise(f'{label} 不能为空。{_REMEDIATION}')
    lowered = normalized.lower()
    if lowered in _ROOT_PARENT_ALIASES:
        return '/'
    if is_cloud_file_id(normalized):
        return normalized
    _emit_stderr_and_raise(_format_invalid_id(normalized, label=label, index=None))


def validate_cloud_file_ids(
    file_ids: Iterable[str],
    *,
    context: str = '',
    field_name: str = 'fileId',
) -> list[str]:
    """批量校验云盘 fileId，去重并保持首次出现顺序。"""
    label = context or field_name
    ordered: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(file_ids, start=1):
        normalized = str(raw or '').strip()
        if not normalized:
            _emit_stderr_and_raise(f'{label} 第 {index} 项为空。{_REMEDIATION}')
        if normalized.lower() in _ROOT_PARENT_ALIASES or normalized == '/':
            _emit_stderr_and_raise(
                f'{label} 第 {index} 项为根目录标识 {normalized!r}，须传入具体文件夹 fileId。{_REMEDIATION}'
            )
        if not is_cloud_file_id(normalized):
            _emit_stderr_and_raise(_format_invalid_id(normalized, label=label, index=index))
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def validate_cloud_parent_file_id(parent_file_id: str, *, context: str = 'parentFileId') -> str:
    """校验父目录：``/`` 或 ``root`` 表示根目录，否则按云盘 fileId 规则校验。"""
    return validate_cloud_file_id(parent_file_id, context=context)
