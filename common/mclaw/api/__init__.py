#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.api —— 同步/异步接口基础类模版 + 联邦式 Service 架构。

详见 README.md。所有 import 以顶层 common/ 目录为 sys.path 根。

架构要点：
  - 每个子包 owns 自己的 ``ApiRegistry`` 实例（无全局单例）
  - ``ApiDispatcher`` 联邦各子 registry，提供双入口调用（属性链 + dotted execute）
"""

from mclaw.api.base.base_sync_api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.base.base_async_api import (
    AsyncSubmitRequest,
    AsyncSubmitResponse,
    AsyncPollResponse,
    BaseAsyncApi,
)
from mclaw.api.base.base_xml_api import BaseXmlSyncApi, XmlRequest, XmlResponse
from mclaw.api.registry import ApiRegistry
from mclaw.api.dispatcher import ApiDispatcher

# 触发子技能包内所有叶子注册（副作用：各子包创建自治 registry + 注册叶子 API）。
# 新增子技能包时在此追加一行：from . import <skill_name>
from . import search_fusion  # noqa: F401
from . import operation  # noqa: F401
from . import search  # noqa: F401
from . import image_tool  # noqa: F401
from . import personal_saas  # noqa: F401
from . import album  # noqa: F401

__all__ = [
    # 基类与 dataclass
    'BaseSyncApi',
    'SyncRequest',
    'SyncResponse',
    'BaseAsyncApi',
    'AsyncSubmitRequest',
    'AsyncSubmitResponse',
    'AsyncPollResponse',
    'BaseXmlSyncApi',
    'XmlRequest',
    'XmlResponse',
    # 注册表与调度器
    'ApiRegistry',
    'ApiDispatcher',
]
