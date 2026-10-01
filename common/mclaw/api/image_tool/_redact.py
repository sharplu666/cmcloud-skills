#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_tool 异步接口终态日志脱敏。

image_tool 下返回 ``resultList/fileInfoList`` 结构的异步接口（ai_avatar /
ai_retouch / ai_expand_image / image_comic_style 等），其响应含超长的 S3 预签名
URL（``content`` / ``thumbnailUrl`` / ``fileUrlList``）和哈希串
（``contentHashAlgorithm``），完整打印会污染日志。

本模块提供 ``redact_image_tool_result(raw)``，递归把这些字段遮蔽为 ``***``，
仅作用于日志展示，``response.raw`` 与接口返回值不受影响。

风格对齐 ``search_fusion/_redact.py``。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

__all__ = ['IMAGE_TOOL_REDACT_KEYS', 'redact_image_tool_result']


# 需脱敏的响应字段：
# - contentHashAlgorithm: fileInfoList[].contentHashAlgorithm（哈希串）
# - content / thumbnailUrl: fileInfoList[] 内的 S3 预签名 URL
# - fileUrlList: resultList[] 下的签名 URL 列表
IMAGE_TOOL_REDACT_KEYS: Tuple[str, ...] = (
    'contentHashAlgorithm',
    'content',
    'thumbnailUrl',
    'fileUrlList',
)

_REDACT = '***'


def _redact_value(value: Any) -> Any:
    """命中脱敏 key 的值处理：list 逐 str 元素替换，scalar 整体 ``***``。"""
    if isinstance(value, list):
        return [_REDACT if isinstance(x, str) else _redact_recursive(x) for x in value]
    return _REDACT


def _redact_recursive(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (_redact_value(v) if k in IMAGE_TOOL_REDACT_KEYS else _redact_recursive(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_recursive(v) for v in obj]
    return obj


def redact_image_tool_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """构造 image_tool 异步接口日志友好的 result dict。

    递归遍历 ``raw``，命中 ``IMAGE_TOOL_REDACT_KEYS`` 的字段：
      - list 值 → 逐 str 元素替换为 ``***``（保留列表结构与元素数）
      - scalar 值 → 整体替换为 ``***``

    其余字段（``fileId`` / ``name`` / ``size`` / ``category`` / ``algorithmCode``
    / ``tokenUsage`` 等）原样保留。返回新 dict，入参 ``raw`` 不被修改。

    Args:
        raw: 原始响应 dict（通常是 ``response.raw``）。

    Returns:
        与 ``raw`` 同构的精简副本；若 ``raw`` 非 dict 则原样返回。
    """
    if not isinstance(raw, dict):
        return raw
    return _redact_recursive(raw)
