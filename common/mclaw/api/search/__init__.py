#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search —— 查询类 API（自治 registry 模式）。

本子包 owns 自己的 ``search_api_registry``。
已注册叶子：
  - get_async_task_status_api → get_async_task_status
  - reading_record_list_api → reading_record_list
"""

from mclaw.api.registry import ApiRegistry

#: 本子包自治注册表
search_api_registry = ApiRegistry(name='search')

from . import get_async_task_status_api  # noqa: F401  副作用：注册
from . import reading_record_list_api  # noqa: F401  副作用：注册

__all__ = ['search_api_registry']
