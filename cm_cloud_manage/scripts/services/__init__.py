#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cm_cloud_manage Service 层 —— 按业务域拆分的编排模块。

子模块：
  - ``search`` / ``file`` / ``upload``：业务编排（须注入 dispatcher）
  - ``client``：dispatcher 单例与 ``api_*`` 对外契约（CLI 调用入口）
"""

from __future__ import annotations

import os
import sys

_SCRIPTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from utils.config import (
    BATCH_SUBREQUEST_MAX,
    MERGE_SEARCH_PAGE_SIZE,
    SEARCH_IMAGE_PAGE_SIZE,
)
from mclaw.shared.postprocess.merge_normalize import (
    merge_file_row_normalize,
    normalize_check_exists_data,
    parse_batch_get_src_file,
)
from services.atomic.file import (
    batch_check_exists,
    batch_download_url,
    batch_file_update,
    batch_get,
    batch_get_all,
    batch_get_path,
    check_exists,
)
from services.atomic.search import (
    build_search_file_param_v3,
    normalize_page_after_input,
    page_after_to_cli_cursor,
    search_merge_file,
    search_merge_image,
)
from services.atomic.upload import create_folder, file_complete, file_create
from services.atomic.client import (
    api_batch_check_exists,
    api_batch_copy_async,
    api_batch_download_url,
    api_batch_file_update,
    api_batch_get,
    api_batch_get_all,
    api_batch_get_path,
    api_batch_move_async,
    api_check_exists,
    api_create_folder,
    api_file_complete,
    api_file_create,
    api_search_merge_file,
    api_task_get,
    build_search_file_param_v3
)

__all__ = [
    'BATCH_SUBREQUEST_MAX',
    'MERGE_SEARCH_PAGE_SIZE',
    'SEARCH_IMAGE_PAGE_SIZE',
    'batch_check_exists',
    'batch_download_url',
    'batch_file_update',
    'batch_get',
    'batch_get_all',
    'batch_get_path',
    'build_search_file_param_v3',
    'check_exists',
    'create_folder',
    'file_complete',
    'file_create',
    'merge_file_row_normalize',
    'normalize_check_exists_data',
    'normalize_page_after_input',
    'page_after_to_cli_cursor',
    'parse_batch_get_src_file',
    'search_merge_file',
    'search_merge_image',
    'api_batch_check_exists',
    'api_batch_copy_async',
    'api_batch_download_url',
    'api_batch_file_update',
    'api_batch_get',
    'api_batch_get_all',
    'api_batch_get_path',
    'api_batch_move_async',
    'api_check_exists',
    'api_create_folder',
    'api_file_complete',
    'api_file_create',
    'api_search_merge_file',
    'api_task_get'
]
