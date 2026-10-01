#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已注册桶名校验与面向 Agent/CLI 的友好报错。"""

from __future__ import annotations

from mclaw.shared.organize.bucket.cli_help import format_bucket_catalog_short
from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY

# 模型/用户常传的分类简称 → 已注册桶名（勿传 time/thing 等别名）
_BUCKET_ALIASES: dict[str, str] = {
    'thing': 'thingLabelList',
    'things': 'thingLabelList',
    'label': 'thingLabelList',
    'labels': 'thingLabelList',
    'people': 'peopleNameList',
    'person': 'peopleNameList',
    'relationship': 'relationshipNameList',
    'relationships': 'relationshipNameList',
    'object': 'objectList',
    'objects': 'objectList',
    'extension': 'fileExtension',
    'ext': 'fileExtension',
    'time': 'month',
    'date': 'month',
}


def suggest_registered_bucket_name(name: str) -> str | None:
    """无效桶名时给出唯一建议；无法确定时返回 None。"""
    key = str(name or '').strip()
    if not key or key in BUCKET_REGISTRY:
        return None
    alias = _BUCKET_ALIASES.get(key)
    if alias and alias in BUCKET_REGISTRY:
        return alias
    lower = key.lower()
    prefix_matches = [b for b in BUCKET_REGISTRY if b.lower().startswith(lower)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    substring_matches = [
        b for b in BUCKET_REGISTRY
        if lower in b.lower() and b.lower() != lower
    ]
    if len(substring_matches) == 1:
        return substring_matches[0]
    return None


def format_invalid_bucket_message(name: str, *, field: str = '--bucket') -> str:
    """生成短而可操作的无效桶名说明（不含完整注册表 dump）。"""
    key = str(name or '').strip()
    suggestion = suggest_registered_bucket_name(key)
    if suggestion:
        return (
            f'{field} 无效：{key!r} 不是已注册桶名；'
            f'请改用 {suggestion!r}（例如 search_image "…" --bucket {suggestion}）'
        )
    return (
        f'{field} 无效：{key!r} 不是已注册桶名。'
        f'须传完整桶名，常用 month、year、city、peopleNameList、thingLabelList；'
        f'分类：{format_bucket_catalog_short()}。'
        f'规则见 cm_cloud_organize/CLUSTERING-RULES.md'
    )


def validate_registered_bucket_name(name: str, *, field: str = '--bucket') -> None:
    """合法则静默；非法则 ``ValueError`` 附带友好文案。"""
    key = str(name or '').strip()
    if key not in BUCKET_REGISTRY:
        raise ValueError(format_invalid_bucket_message(key, field=field))


def validate_registered_bucket_names(names: list[str], *, field: str = '--buckets') -> None:
    for item in names:
        validate_registered_bucket_name(item, field=field)
