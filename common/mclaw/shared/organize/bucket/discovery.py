#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""维度发现与解析。

将分类名或桶名的混合列表解析为桶名列表：

- ``resolve_dimensions(spec)``：将分类名与桶名的混合列表解析为桶名列表
  （如 ``['time', 'city']`` → ``['month', 'city']``，分类名取默认桶）。
- ``bucket_category_of(bucket_name)``：返回桶名所属的 ``BucketCategoryInfo``。

解析基于 ``BUCKET_REGISTRY`` 实时状态。未知维度或分类无默认桶时抛 ``ValueError``。
"""

from __future__ import annotations

from typing import List, Optional

from mclaw.shared.organize.bucket.base import Bucketer
from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY, BucketCategoryInfo


def resolve_dimensions(spec: List[str]) -> List[str]:
    """把混合输入（分类名或桶名）解析为桶名列表，保持原顺序。

    输入元素可以是：

    - **分类名**（如 ``'time'`` / ``'location'`` / ``'attr'``）
      → 取该分类的默认桶（``BucketCategoryInfo.default``）；
        若分类未声明默认桶则抛 ``ValueError``
    - **具体桶名**（如 ``'month'`` / ``'city'`` / ``'make'``）
      → 原样保留

    混合输入合法：

        resolve_dimensions(['time', 'province'])
        # → ['month', 'province']
        #   'time' 走分类默认 month；'province' 是具体桶名直接保留

    Args:
        spec: 维度规格列表，每个元素为分类名或桶名。

    Returns:
        桶名列表，长度与 ``spec`` 相同，顺序一致。

    Raises:
        ValueError: 元素既不是已注册分类名，也不是已注册桶名；
            或元素是分类名但该分类无默认桶。
    """
    if not spec:
        raise ValueError('spec 不能为空')

    cats = BUCKET_REGISTRY.categories()
    cat_by_name = {info.name: info for info in cats.values()}
    resolved: List[str] = []

    for item in spec:
        if item in cat_by_name:
            default = cat_by_name[item].default
            if default is None:
                raise ValueError(
                    f'分类 {item!r} 未声明默认桶，请显式指定桶名，'
                    f'可选成员：{cat_by_name[item].members}'
                )
            resolved.append(default)
        elif item in BUCKET_REGISTRY:
            resolved.append(item)
        else:
            known_cats = list(cat_by_name.keys())
            known_buckets = list(BUCKET_REGISTRY)
            raise ValueError(
                f'未知维度 {item!r}：既不是分类名（{known_cats}），'
                f'也不是桶名（{known_buckets}）'
            )
    return resolved


def bucket_category_of(bucket_name: str) -> Optional[BucketCategoryInfo]:
    """桶名 → 所属分类信息。

    用于 introspection：给定一个桶名，查它属于哪个分类、该分类的默认桶是谁、
    是否多值等。供 UI 展示维度元信息、调用方做参数校验。

    Args:
        bucket_name: 桶名，如 ``'city'`` / ``'livePhoto'``。

    Returns:
        所属 ``BucketCategoryInfo``；若桶未注册返回 ``None``。
    """
    for info in BUCKET_REGISTRY.categories().values():
        if bucket_name in info.members:
            return info
    return None


def list_categories() -> List[BucketCategoryInfo]:
    """列出所有已注册分类（按分类名字母序）。

    便捷入口，等价于 ``list(BUCKET_REGISTRY.categories().values())``，
    但保证排序稳定（``BUCKET_REGISTRY.categories()`` 返回 dict，Python 3.7+
    虽保序但顺序取决于桶注册顺序，本函数显式按分类名排序便于展示）。
    """
    return sorted(
        BUCKET_REGISTRY.categories().values(),
        key=lambda c: c.name,
    )
