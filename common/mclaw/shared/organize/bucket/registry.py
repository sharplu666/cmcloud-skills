#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桶注册表与 ``@register_bucket`` 装饰器。

``BUCKET_REGISTRY`` 是 ``BucketRegistry`` 单例，所有读取始终反映当前注册状态，
无快照、无缓存、无导入期冻结。

注册新桶：

    1. 在 ``bucket/`` 下新建模块，定义 ``Bucketer`` 子类并实现 ``bucket_key``
    2. 用 ``@register_bucket('名称')`` 装饰该类
    3. 在 ``bucket/__init__.py`` 中 ``from . import 模块`` 触发注册
"""


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Tuple, Type

from mclaw.shared.organize.bucket.base import Bucketer


@dataclass(frozen=True)
class BucketCategoryInfo:
    """桶分类视图（由 ``BucketRegistry.categories`` 派生，非用户直接构造）。

    字段说明（与 ``Bucketer`` 类属性一一对应，聚合分类下的所有成员）：

    Attributes:
        name: 分类名，等同 ``Bucketer.bucket_category``。如 ``'time'`` / ``'location'``。
        bucket_label: 分类中文标签，取自该分类下**首个成员**的 ``Bucketer.bucket_label``；
            若成员未声明则回退为分类名 ``name``。如 ``'时间'`` / ``'地点'``。
        members: 该分类下所有已注册桶名（按字母序），如 ``('day', 'month', 'year')``。
        default: 该分类的默认桶名（即 ``is_default_in_bucket_category=True`` 的成员）；
            无成员声明默认时为 ``None``，调用方需显式指定桶名。
        is_multi_value: 该分类下是否存在多值桶（一个 file 可同时进多个桶）。
    """

    name: str
    bucket_label: str
    members: Tuple[str, ...] = field(default_factory=tuple)
    default: Optional[str] = None
    is_multi_value: bool = False


class BucketRegistry:
    """桶注册表的活容器。

    所有访问都实时反映当前注册状态 —— 没有任何快照、缓存或导入期冻结。
    """

    def __init__(self) -> None:
        self._buckets: Dict[str, Type[Bucketer]] = {}

    # ------------------ 写入 ------------------

    def register(self, name: str, cls: Type[Bucketer]) -> None:
        """注册一个桶。重复注册同名桶会抛 ``ValueError``。"""
        if not issubclass(cls, Bucketer):
            raise TypeError(f'仅 Bucketer 子类可注册，收到 {cls!r}')
        if name in self._buckets:
            raise ValueError(
                f'桶名 {name!r} 已被 {self._buckets[name].__name__} 占用，'
                f'不可重复注册'
            )
        self._buckets[name] = cls

    # ------------------ 查询 ------------------

    def build(self, name: str) -> Bucketer:
        """按桶名构造 ``Bucketer`` 实例。

        返回的实例本身 callable（``__call__`` → ``bucket_key``），可无缝替代
        旧的 ``Callable[[File], str | list[str]]`` 接口。
        """
        cls = self._buckets.get(name)
        if cls is None:
            from mclaw.shared.organize.bucket.bucket_validation import format_invalid_bucket_message

            raise ValueError(format_invalid_bucket_message(name, field='bucket'))
        return cls()

    def get_class(self, name: str) -> Type[Bucketer]:
        """按桶名取回原始类（用于 introspection 或子类化扩展）。"""
        if name not in self._buckets:
            from mclaw.shared.organize.bucket.bucket_validation import format_invalid_bucket_message

            raise ValueError(format_invalid_bucket_message(name, field='bucket'))
        return self._buckets[name]

    def categories(self) -> Dict[str, BucketCategoryInfo]:
        """从已注册桶派生分类视图（实时计算，无缓存）。

        每个已注册桶按其 ``bucket_category`` 类属性归入对应分类，聚合输出
        ``BucketCategoryInfo``。这是分类信息的**唯一真理源** —— 不维护
        第二张表，新增桶时声明 ``bucket_category`` 即自动纳入。

        Returns:
            ``{分类名: BucketCategoryInfo}`` 字典。``misc`` 分类为未声明
            ``bucket_category`` 的桶的默认归处。
        """
        raw: Dict[str, dict] = {}
        for bucket_name, cls in self._buckets.items():
            cat_name = cls.bucket_category
            cat = raw.setdefault(cat_name, {
                'name': cat_name,
                'bucket_label': cls.bucket_label or cat_name,
                'members': [],
                'default': None,
                'is_multi_value': cls.is_multi_value,
            })
            cat['members'].append(bucket_name)
            cat['is_multi_value'] = cat['is_multi_value'] or cls.is_multi_value
            # 取首个声明了 label 的成员作为分类展示标签（避免空 label）
            if not cat['bucket_label'] or cat['bucket_label'] == cat_name:
                cat['bucket_label'] = cls.bucket_label or cat_name
            if cls.is_default_in_bucket_category:
                cat['default'] = bucket_name
        return {
            k: BucketCategoryInfo(
                name=v['name'],
                bucket_label=v['bucket_label'],
                members=tuple(sorted(v['members'])),
                default=v['default'],
                is_multi_value=v['is_multi_value'],
            )
            for k, v in raw.items()
        }

    # ------------------ 容器协议（实时） ------------------

    def __iter__(self) -> Iterator[str]:
        return iter(self._buckets)

    def __len__(self) -> int:
        return len(self._buckets)

    def __contains__(self, name: object) -> bool:
        return name in self._buckets

    def __repr__(self) -> str:
        return f'BucketRegistry({list(self._buckets)})'


#: 全局单例。所有 ``@register_bucket`` 装饰器都写入它；
#: 所有调用方都从它读取。活容器，无快照。
BUCKET_REGISTRY: BucketRegistry = BucketRegistry()


# ---------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------

def register_bucket(name: str) -> Callable[[Type[Bucketer]], Type[Bucketer]]:
    """类装饰器。将 ``Bucketer`` 子类注册到 ``BUCKET_REGISTRY``。"""
    def decorator(cls: Type[Bucketer]) -> Type[Bucketer]:
        BUCKET_REGISTRY.register(name, cls)
        return cls
    return decorator


def build_bucket_fn(name: str) -> Bucketer:
    """按桶名构造 ``Bucketer`` 实例（``BUCKET_REGISTRY.build`` 的函数式入口）。"""
    return BUCKET_REGISTRY.build(name)


def get_bucket_class(name: str) -> Type[Bucketer]:
    """按桶名取回原始类（``BUCKET_REGISTRY.get_class`` 的函数式入口）。"""
    return BUCKET_REGISTRY.get_class(name)
