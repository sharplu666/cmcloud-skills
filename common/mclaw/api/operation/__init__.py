#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""operation —— 文件操作类 API（自治 registry 模式）。

本子包 owns 自己的 ``operation_api_registry``。
已注册叶子：
  - batch_move_files_api → batch_move_files（异步，JSON submit + JSON 轮询）
  - photo_organize_submit_api → submit_photo_organize_task（multipart 提交，同步返回 taskId）
  - photo_organize_query_api → query_photo_organize_task（JSON 查询，同步返回 taskInfo + results）
  - photo_organize_retry_api → retry_photo_organize_task（JSON，对失败/部分失败任务重试，仅处理失败文件）
  - session_folder_name_api → resolve_session_folder_name（JSON，同步查询/生成会话文件夹名称）
"""

from mclaw.api.registry import ApiRegistry

#: 本子包自治注册表
operation_api_registry = ApiRegistry(name='operation')

from . import batch_move_files_api  # noqa: F401  副作用：注册
from . import photo_organize_submit_api  # noqa: F401  副作用：注册
from . import photo_organize_query_api   # noqa: F401  副作用：注册
from . import photo_organize_retry_api   # noqa: F401  副作用：注册
from . import session_folder_name_api    # noqa: F401  副作用：注册

__all__ = ['operation_api_registry']
