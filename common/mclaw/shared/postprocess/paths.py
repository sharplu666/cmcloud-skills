#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云盘路径规范化与 MClaw 可写前缀校验（纯函数，无配置依赖）。

调用方显式传入 ``allowed_dir``（如 ``/AI空间/MClaw空间``），本模块不 import manage config。

用法::

    from mclaw.shared.postprocess.paths import (
        CloudPathError,
        assert_mclaw_path_prefix,
        join_cloud_dir_path,
        normalize_cloud_dir_path,
        split_cloud_dir_path,
    )

    parts = split_cloud_dir_path('/AI空间/MClaw空间/对话文件')
    assert_mclaw_path_prefix(parts, allowed_dir='/AI空间/MClaw空间', action='创建目录')
    path = normalize_cloud_dir_path('root:/AI空间/MClaw空间/')  # -> '/AI空间/MClaw空间'
"""

from __future__ import annotations

from typing import Any


class CloudPathError(RuntimeError):
    """云盘路径不合法或不在允许前缀内。"""


def normalize_name_path(raw: Any) -> str:
    """去掉 ``root:`` 前缀（若有），返回剩余路径字符串。"""
    path = str(raw or '').strip()
    return path[5:] if path.startswith('root:') else path


def normalize_cloud_dir_path(raw: str) -> str:
    """规范化云盘目录路径：单个前导 ``/``、无尾部 ``/``、保留段内空格。

    空输入返回 ``''``；仅由斜杠组成时返回 ``'/'``。
    """
    raw = normalize_name_path(raw)
    text = str(raw or '').strip()
    if not text:
        return ''
    parts = [part for part in text.split('/') if part]
    if not parts:
        return '/'
    return '/' + '/'.join(parts)


def compact_segment_name(name: str) -> str:
    """去掉段名中的全部空白，用于同级「带空格 / 不带空格」目录匹配。"""
    return ''.join(ch for ch in str(name or '') if not ch.isspace())


def split_cloud_dir_path(raw: str) -> list[str]:
    """拆分云盘路径为段列表，保留各级目录名中的空格。"""
    path = normalize_name_path(str(raw or '').strip()).replace('\\', '/')
    while '//' in path:
        path = path.replace('//', '/')
    path = path.strip()
    if path.startswith('/'):
        path = path[1:]
    if path.endswith('/'):
        path = path[:-1]
    return [part for part in path.split('/') if part != '']


def join_cloud_dir_path(parts: list[str]) -> str:
    """将路径段拼回以 ``/`` 开头的云盘路径；空列表返回 ``'/'``。"""
    if not parts:
        return '/'
    return '/' + '/'.join(parts)


def assert_mclaw_path_prefix(
    parts: list[str],
    *,
    allowed_dir: str,
    action: str = '操作',
    error_cls: type[Exception] = CloudPathError,
) -> None:
    """断言 ``parts`` 以 ``allowed_dir`` 为前缀（段名空白折叠后比较）。

    Args:
        parts: 已拆分的路径段（见 :func:`split_cloud_dir_path`）。
        allowed_dir: 允许的根路径，如 ``/AI空间/MClaw空间``（必填，由调用方传入）。
        action: 错误文案中的动作名，如 ``'创建目录'``。
        error_cls: 失败时抛出的异常类型，默认 :class:`CloudPathError`。

    Raises:
        error_cls: 段数不足或任一级段名不匹配时。
    """
    required = split_cloud_dir_path(allowed_dir)
    if len(parts) < len(required):
        raise error_cls(
            f'{action}失败：路径必须以 "{allowed_dir}" 开头，'
            f'当前为 "{join_cloud_dir_path(parts)}"'
        )
    for index, required_name in enumerate(required):
        if compact_segment_name(parts[index]) != compact_segment_name(required_name):
            raise error_cls(
                f'{action}失败：路径必须以 "{allowed_dir}" 开头，'
                f'第 {index + 1} 级应为 {required_name!r}，当前为 {parts[index]!r}'
            )


__all__ = [
    'CloudPathError',
    'normalize_name_path',
    'normalize_cloud_dir_path',
    'compact_segment_name',
    'split_cloud_dir_path',
    'join_cloud_dir_path',
    'assert_mclaw_path_prefix',
]
