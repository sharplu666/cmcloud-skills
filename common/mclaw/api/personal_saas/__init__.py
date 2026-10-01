#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""personal_saas —— 个人云 SaaS 文件类 API（自治 registry 模式）。

本子包 owns 自己的 ``personal_saas_api_registry``，所有叶子 API 装饰器指向它。
顶层 ``ApiDispatcher`` 联邦本 registry 后即可通过
``d.personal_saas.<leaf>(req)`` 或 ``d.execute('personal_saas.<leaf>', req)`` 调用。

已注册叶子（10 项，9 同步 + 1 异步）：
  - batch_get / batch_check_exists / batch_get_download_url / file_create /
    file_complete / create_folder / batch_update / query_file_schedules /
    get_path（同步）
  - batch_copy（异步，提交后轮询 task/get）
"""

from mclaw.api.registry import ApiRegistry

#: 本子包自治注册表
personal_saas_api_registry = ApiRegistry(name='personal_saas')

from . import batch_get_api  # noqa: F401  副作用：注册
from . import batch_check_exists_api  # noqa: F401
from . import batch_get_download_url_api  # noqa: F401
from . import file_create_api  # noqa: F401
from . import file_complete_api  # noqa: F401
from . import create_folder_api  # noqa: F401
from . import batch_update_api  # noqa: F401
from . import query_file_schedules_api  # noqa: F401
from . import query_personal_dynamic_api  # noqa: F401
from . import video_preview_api  # noqa: F401
from . import batch_copy_api  # noqa: F401
from . import get_path_api  # noqa: F401

__all__ = ['personal_saas_api_registry']
