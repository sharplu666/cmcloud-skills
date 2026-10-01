#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶层 API 调度器：联邦各子包的 ``ApiRegistry``，提供双入口调用。

架构要点（详见 ``registry.py`` 模块 docstring）：

  - 每个子包 owns 自己的 ``ApiRegistry`` 实例（无全局单例）
  - ``ApiDispatcher`` 在 ``__init__`` 里**显式列举**要联邦的子 registry，
    通过 ``_mount`` 把每个子 registry 包成 ``_SubDispatcher`` 挂为实例真实属性
  - 调用方双入口：

        d = ApiDispatcher(host=..., auth_fn=...)

        # 入口 1：属性链（一级命名空间是真实属性，IDE 可补全）
        d.search_fusion.search_merge_file(req)

        # 入口 2：dotted 字符串（可 grep、可动态派发、便于跨域批处理）
        d.execute('search_fusion.search_merge_file', req)

  - 两条入口在 ``_SubDispatcher._execute`` 收敛到同一条实例构造 + 调用路径，
    行为完全等价

新增子域的成本（显式列举的有意代价，避免隐式扫描）：

  1. 子包 ``__init__.py`` 创建 ``xxx_api_registry = ApiRegistry(name='xxx')``
  2. 本文件 ``ApiDispatcher.__init__`` 追加 ``from mclaw.api.xxx import xxx_api_registry``
     与 ``self._mount('xxx', xxx_api_registry)`` 两行
  3. 在 ``ApiDispatcher`` 类体顶部补一行 ``xxx: _SubDispatcher`` 类型注解
     （供 IDE 静态跳转/补全；运行时实例仍由 ``_mount`` 创建）
"""

from __future__ import annotations

from functools import partial
from typing import Any, Callable, Dict, List, Optional, Union

from mclaw.api.base.base_sync_api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.base.base_async_api import (
    BaseAsyncApi,
    AsyncSubmitRequest,
    AsyncPollResponse,
)
from mclaw.api.base.base_xml_api import BaseXmlSyncApi, XmlRequest, XmlResponse
from mclaw.api.registry import ApiRegistry


__all__ = ['ApiDispatcher']


# 同步/异步 API 实例的联合类型
_ApiInstance = Union[BaseSyncApi, BaseAsyncApi, BaseXmlSyncApi]


class _SubDispatcher:
    """子命名空间调用门面。由 ``ApiDispatcher._mount`` 创建，挂为 dispatcher 的真实属性。

    通过 ``__getattr__`` 在**本命名空间内**派发叶子调用。与旧版扁平
    ``ApiClient.__getattr__`` 的关键区别：这里的 ``__getattr__`` 作用域有界——
    调用方已显式导航到某个子命名空间（如 ``d.search_fusion``），叶子解析只在该
    registry 范围内进行，不再是无差别 catch-all。
    """

    def __init__(self, registry: ApiRegistry, parent: 'ApiDispatcher') -> None:
        self._registry = registry
        self._parent = parent

    @property
    def name(self) -> str:
        """命名空间名（透传自 registry）。"""
        return self._registry.name

    def execute(
        self,
        leaf_name: str,
        request: Union[SyncRequest, AsyncSubmitRequest, XmlRequest],
        **kwargs: Any,
    ) -> Union[SyncResponse, AsyncPollResponse, XmlResponse]:
        """显式 execute 入口，与 ``__getattr__`` 派发等价。

        适合需要把 leaf 名作为变量传递的场景：
            sub.execute(leaf_name, req)
        """
        return self._execute(leaf_name, request, **kwargs)

    def _execute(
        self,
        leaf_name: str,
        request: Union[SyncRequest, AsyncSubmitRequest, XmlRequest],
        **kwargs: Any,
    ) -> Union[SyncResponse, AsyncPollResponse, XmlResponse]:
        """内部共享路径：从父 dispatcher 取实例（带缓存）并调用。"""
        instance = self._parent._get_instance(
            self._registry.name, leaf_name, self._registry
        )
        return instance.execute(request, **kwargs)

    def list_apis(self) -> List[str]:
        """本命名空间下所有叶子名。"""
        return self._registry.list_apis()

    def __getattr__(self, leaf_name: str) -> Callable[..., Any]:
        """属性式访问：``sub.search_merge_file(req)`` 等价于 ``sub.execute('search_merge_file', req)``。

        仅对本 registry 已注册的叶子名生效；其他名字抛 ``AttributeError``。

        注意：``__getattr__`` 只在常规属性查找失败时触发，所以 ``self._registry`` /
        ``self.execute`` 等不受影响。``_`` 前缀属性直接抛 ``AttributeError``，
        避免递归与 dunder 查询干扰。
        """
        if leaf_name.startswith('_'):
            raise AttributeError(leaf_name)
        if leaf_name not in self._registry:
            raise AttributeError(
                f'{self._registry.name!r} 无 API {leaf_name!r}'
                f'（已注册：{self._registry.list_apis()}）'
            )
        return partial(self._execute, leaf_name)

    def __repr__(self) -> str:
        return (
            f'_SubDispatcher({self._registry.name!r}, '
            f'leaves={self._registry.list_apis()})'
        )


class ApiDispatcher:
    """顶层 API 调度器。联邦各子包的 ``ApiRegistry``，对外提供双入口调用。

    持有 ``host`` / ``auth_fn`` / ``logger`` 公共参数，按命名空间 + 叶子名从对应
    ``ApiRegistry`` 取子类、构造实例（默认缓存）、代理 ``execute``。调用方只需
    构造一次 ``ApiDispatcher``。

    双入口示例：

        from mclaw.api import ApiDispatcher

        d = ApiDispatcher(
            host='https://api.example.com',
            auth_fn=get_auth_header,
            logger=my_logger,           # 可选
            cache_instances=True,       # 可选，默认 True
        )

        # 属性链（推荐日常使用；一级命名空间是真实属性）
        resp = d.search_fusion.search_merge_file(req)

        # dotted 字符串（推荐动态派发或跨域批处理时使用）
        resp = d.execute('search_fusion.search_merge_file', req)

    同步 API 返回 ``SyncResponse``，异步 API 返回 ``AsyncPollResponse``，
    由 registry 根据 ``issubclass`` 自动判定，调用方无感知。

    注意：
      - ``host`` / ``auth_fn`` 对所有命名空间共享。若需 per-api 配置，请直接
        构造具体子类实例，不走 ``ApiDispatcher``。
      - 一级命名空间（如 ``d.search_fusion``）在类体顶部以类型注解声明
        （``search_fusion: _SubDispatcher``），实例真实属性仍由 ``_mount`` 在
        ``__init__`` 创建。注解仅供 IDE 静态跳转/补全——裸注解不创建类属性，
        故不影响实例属性查找。新增子域时记得在下方注解块补一行。
        二级叶子（如 ``d.search_fusion.search_merge_file``）依赖 ``_SubDispatcher.__getattr__``，
        IDE 无法静态补全，需要类型提示时优先用 ``d.execute('ns.leaf', req)``。
    """

    # ──────────────────────────── 一级命名空间注解（IDE 跳转用）────────────────────────────
    # 裸注解：仅写入 __annotations__，不创建类属性，不遮蔽 _mount 设的实例属性。
    # 新增子域：在此追加一行 ``xxx: _SubDispatcher``，并在 __init__ 里 _mount。
    search_fusion: _SubDispatcher
    operation: _SubDispatcher
    search: _SubDispatcher
    image_tool: _SubDispatcher
    personal_saas: _SubDispatcher
    album: _SubDispatcher

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger: Optional[Any] = None,
        *,
        cache_instances: bool = True,
    ) -> None:
        self._host = host
        self._auth_fn = auth_fn
        self._logger = logger
        self._cache_instances = cache_instances
        # key: 'namespace.leaf' -> 已构造的 Api 实例（cache_instances=True 时复用）
        self._instances: Dict[str, _ApiInstance] = {}
        # namespace 名 -> _SubDispatcher
        self._namespaces: Dict[str, _SubDispatcher] = {}

        # ──────────────────────────── 联邦子注册表 ────────────────────────────
        # 新增子域：① 在此追加一行 import；② 追加一行 self._mount(...)
        from mclaw.api.search_fusion import search_fusion_api_registry
        from mclaw.api.operation import operation_api_registry
        from mclaw.api.search import search_api_registry
        from mclaw.api.image_tool import image_tool_api_registry
        from mclaw.api.personal_saas import personal_saas_api_registry
        from mclaw.api.album import album_api_registry

        self._mount('search_fusion', search_fusion_api_registry)
        self._mount('operation', operation_api_registry)
        self._mount('search', search_api_registry)
        self._mount('image_tool', image_tool_api_registry)
        self._mount('personal_saas', personal_saas_api_registry)
        self._mount('album', album_api_registry)

    # ──────────────────────────── 内部挂载 ────────────────────────────

    def _mount(self, namespace: str, registry: ApiRegistry) -> _SubDispatcher:
        """挂载子 registry：包成 ``_SubDispatcher``，注册到 ``_namespaces``，
        并通过 ``object.__setattr__`` 暴露为实例真实属性（IDE 可补全一级）。

        用 ``object.__setattr__`` 而非 ``setattr`` 是为了在未来若给本类加
        ``__setattr__`` 拦截时不被误伤；当前类无此拦截，二者等价。
        """
        if registry.name != namespace:
            raise ValueError(
                f'命名空间名 {namespace!r} 与 registry.name {registry.name!r} 不一致'
            )
        if namespace in self._namespaces:
            raise ValueError(f'命名空间 {namespace!r} 已挂载')
        sub = _SubDispatcher(registry, self)
        self._namespaces[namespace] = sub
        object.__setattr__(self, namespace, sub)
        return sub

    def _get_instance(
        self,
        namespace: str,
        leaf_name: str,
        registry: ApiRegistry,
    ) -> _ApiInstance:
        """按命名空间 + 叶子名取实例（缓存命中则复用，否则构造并缓存）。"""
        cache_key = f'{namespace}.{leaf_name}'
        if self._cache_instances and cache_key in self._instances:
            return self._instances[cache_key]
        instance = registry.build(
            leaf_name, self._host, self._auth_fn, self._logger
        )
        if self._cache_instances:
            self._instances[cache_key] = instance
        return instance

    # ──────────────────────────── 公共 API ────────────────────────────

    def execute(
        self,
        dotted_name: str,
        request: Union[SyncRequest, AsyncSubmitRequest, XmlRequest],
    ) -> Union[SyncResponse, AsyncPollResponse, XmlResponse]:
        """dotted 字符串入口：``'namespace.leaf_name'`` → 路由到对应 ``_SubDispatcher``。

        Args:
            dotted_name: 形如 ``'search_fusion.search_merge_file'`` 的全名。
            request: 入参对象（``SyncRequest`` / ``AsyncSubmitRequest`` / ``XmlRequest``）。

        Returns:
            同步 JSON 返回 ``SyncResponse``，异步返回 ``AsyncPollResponse``，XML 返回 ``XmlResponse``。

        Raises:
            ValueError: dotted_name 不含 ``.`` 或命名空间未知。
        """
        namespace, dot, leaf_name = dotted_name.rpartition('.')
        if not dot or not namespace:
            raise ValueError(
                f'dotted_name 须形如 "namespace.leaf"，收到 {dotted_name!r}'
            )
        sub = self._namespaces.get(namespace)
        if sub is None:
            raise ValueError(
                f'未知命名空间 {namespace!r}'
                f'（已知：{list(self._namespaces)}）'
            )
        return sub._execute(leaf_name, request)

    def list_apis(self) -> List[str]:
        """所有已注册 API 的 dotted 全名（按命名空间挂载顺序 + 各 registry 注册顺序）。"""
        return [
            f'{ns_name}.{leaf}'
            for ns_name, sub in self._namespaces.items()
            for leaf in sub._registry
        ]

    def list_namespaces(self) -> List[str]:
        """所有已挂载命名空间名。"""
        return list(self._namespaces)

    def get_sub_dispatcher(self, namespace: str) -> _SubDispatcher:
        """按命名空间名取 ``_SubDispatcher``（也可直接用 ``getattr(d, namespace)``）。"""
        if namespace not in self._namespaces:
            raise ValueError(
                f'未知命名空间 {namespace!r}（已知：{list(self._namespaces)}）'
            )
        return self._namespaces[namespace]

    def __repr__(self) -> str:
        return (
            f'ApiDispatcher(host={self._host!r}, '
            f'namespaces={list(self._namespaces)})'
        )
