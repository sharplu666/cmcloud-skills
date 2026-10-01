#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单命名空间 API 注册表。

设计参考 `dev/skills/cm_cloud_organize/scripts/bucket/registry.py`：活容器、零快照、
类装饰器、类属性携带元信息。同步/异步通过 ``issubclass(cls, BaseSyncApi /
BaseAsyncApi)`` 自动判定，子类无需声明 ``api_kind``。

与旧版的关键差异：**不再有全局 ``API_REGISTRY`` 单例**。每个子包（如
``mclaw.api.search_fusion``）实例化自己的 ``ApiRegistry(name='search_fusion')``，
子 API 装饰器指向本包 registry。顶层调用门面 ``ApiDispatcher`` 联邦各子 registry，
详见 ``mclaw.api/dispatcher.py``。

子包注册模式：

    # mclaw/api/search_fusion/__init__.py
    from mclaw.api.registry import ApiRegistry
    search_fusion_api_registry = ApiRegistry(name='search_fusion')

    # mclaw/api/search_fusion/search_merge_file_api.py
    from mclaw.api.search_fusion import search_fusion_api_registry

    @search_fusion_api_registry.register('search_merge_file')
    class MergeFileSearchApi(BaseSyncApi):
        PATH = '/...'
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, List, Optional, Type, Union

from mclaw.api.base.base_sync_api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.base.base_async_api import (
    BaseAsyncApi,
    AsyncSubmitRequest,
    AsyncPollResponse,
)
from mclaw.api.base.base_xml_api import BaseXmlSyncApi


__all__ = ['ApiRegistry']


# 同步/异步基类的联合类型（注册表存储的值类型）
_BaseApiCls = Type[Union[BaseSyncApi, BaseAsyncApi, BaseXmlSyncApi]]


class ApiRegistry:
    """单个命名空间的 API 注册表活容器（零快照：所有查询实时反映当前注册状态）。

    内部存储 ``leaf_name -> Api 子类``（不是实例）。实例构造延迟到调用时，
    由 ``ApiDispatcher`` 触发。同步/异步通过 ``issubclass`` 自动判定。

    一个 ``ApiRegistry`` 实例对应一个子包（如 ``search_fusion``）。命名空间之间
    互不干扰，便于独立测试与按域联邦。
    """

    def __init__(self, name: str) -> None:
        if not name or '.' in name:
            raise ValueError(
                f'ApiRegistry 名不可为空且不可含 "."（保留给 dispatcher dotted 路径），'
                f'收到 {name!r}'
            )
        self._name = name
        self._leaves: Dict[str, _BaseApiCls] = {}

    @property
    def name(self) -> str:
        """命名空间名（如 ``'search_fusion'``）。"""
        return self._name

    # ──────────────────────────── 写入 ────────────────────────────

    def register(self, leaf_name: str, cls: Optional[_BaseApiCls] = None):
        """注册一个 API 子类作为本命名空间的叶子。

        支持两种用法：

        1. **装饰器工厂**（推荐，配合 ``@`` 使用）::

              @my_registry.register('face_detect')
              class FaceDetectApi(BaseSyncApi):
                  PATH = '/...'

        2. **直接调用**::

              my_registry.register('face_detect', FaceDetectApi)

        Args:
            leaf_name: 叶子名（如 ``'search_merge_file'``），不可含 ``.``。
            cls: ``BaseSyncApi`` 或 ``BaseAsyncApi`` 的子类。装饰器用法下省略，
                由返回的 decorator 接收。

        Raises:
            TypeError: cls 不是 BaseSyncApi/BaseAsyncApi 子类。
            ValueError: leaf_name 含 ``.``，或已被其他类占用。
        """
        if '.' in leaf_name:
            raise ValueError(
                f'叶子名不可含 "."（保留给 dispatcher dotted 路径），收到 {leaf_name!r}'
            )

        def _do_register(cls: _BaseApiCls) -> _BaseApiCls:
            if not (
                issubclass(cls, BaseSyncApi)
                or issubclass(cls, BaseAsyncApi)
                or issubclass(cls, BaseXmlSyncApi)
            ):
                raise TypeError(
                    f'仅 BaseSyncApi/BaseAsyncApi/BaseXmlSyncApi 子类可注册，收到 {cls!r}'
                )
            if leaf_name in self._leaves:
                raise ValueError(
                    f'API 名 {leaf_name!r} 已被 {self._leaves[leaf_name].__name__} 占用，'
                    f'不可重复注册'
                )
            self._leaves[leaf_name] = cls
            return cls

        # 直接调用：register('leaf', cls)
        if cls is not None:
            return _do_register(cls)
        # 装饰器工厂：register('leaf') → 返回 decorator
        return _do_register

    # ──────────────────────────── 查询 ────────────────────────────

    def get_class(self, leaf_name: str) -> _BaseApiCls:
        """按叶子名取回原始类（用于 introspection 或子类化扩展）。"""
        if leaf_name not in self._leaves:
            raise ValueError(
                f'{self._name!r} 仅支持 {list(self._leaves)}，收到 {leaf_name!r}'
            )
        return self._leaves[leaf_name]

    def build(
        self,
        leaf_name: str,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger: Optional[Any] = None,
    ) -> Union[BaseSyncApi, BaseAsyncApi, BaseXmlSyncApi]:
        """按叶子名构造实例（每次调用都新建，不做缓存；缓存由 dispatcher 管理）。"""
        cls = self.get_class(leaf_name)
        return cls(host=host, auth_fn=auth_fn, logger=logger)

    def is_sync(self, leaf_name: str) -> bool:
        """判断叶子是否为同步（BaseSyncApi / BaseXmlSyncApi 子类）。"""
        cls = self.get_class(leaf_name)
        return issubclass(cls, BaseSyncApi) or issubclass(cls, BaseXmlSyncApi)

    def is_async(self, leaf_name: str) -> bool:
        """判断叶子是否为异步（BaseAsyncApi 子类）。"""
        return issubclass(self.get_class(leaf_name), BaseAsyncApi)

    def list_apis(self) -> List[str]:
        """返回本命名空间下所有叶子名（按注册顺序）。"""
        return list(self._leaves)

    def categories(self) -> Dict[str, Dict[str, Any]]:
        """从已注册叶子的类属性派生**域内**分类视图（实时计算，无缓存）。

        返回结构：

            {
                'detect': {
                    'name': 'detect',
                    'label': '检测类',
                    'kind': 'sync',  # 或 'async'
                    'members': ['face_detect', ...],
                },
                ...
            }

        依赖子类的 ``api_category`` / ``api_label`` 类属性（可选，默认 ``'misc'`` / ``''``）。
        同一 category 下若出现 sync 与 async 混合，kind 取首次出现的类别，
        便于在分类粒度上做粗粒度展示；细粒度判定请用 ``is_sync`` / ``is_async``。
        """
        raw: Dict[str, Dict[str, Any]] = {}
        for leaf_name, cls in self._leaves.items():
            cat_name = getattr(cls, 'api_category', 'misc') or 'misc'
            kind = 'sync' if issubclass(cls, (BaseSyncApi, BaseXmlSyncApi)) else 'async'
            entry = raw.setdefault(cat_name, {
                'name': cat_name,
                'label': '',
                'kind': kind,
                'members': [],
            })
            if not entry['label']:
                entry['label'] = getattr(cls, 'api_label', '') or cat_name
            entry['members'].append(leaf_name)
        for entry in raw.values():
            entry['members'] = sorted(entry['members'])
        return raw

    # ──────────────────────────── 容器协议 ────────────────────────────

    def __iter__(self) -> Iterator[str]:
        return iter(self._leaves)

    def __len__(self) -> int:
        return len(self._leaves)

    def __contains__(self, leaf_name: object) -> bool:
        return leaf_name in self._leaves

    def __repr__(self) -> str:
        return f'ApiRegistry({self._name!r}, {list(self._leaves)})'
