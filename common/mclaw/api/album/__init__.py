#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""album —— 智能相册类 API（自治 registry 模式）。

本子包 owns 自己的 ``album_api_registry``，所有叶子 API 装饰器指向它。
顶层 ``ApiDispatcher`` 联邦本 registry 后即可通过
``d.album.<leaf>(req)`` 或 ``d.execute('album.<leaf>', req)`` 调用。

已注册叶子（23 个，全部同步）：
  - image_deduplicate（**同步**，图片去重）
  - image_batch_deduplicate_submit（**multipart 提交，同步返回 taskId**，批量图片去重）
  - image_batch_deduplicate_result（**同步**，查询批量去重任务状态/统计/结果链接）
  - select_photo_submit（**multipart 提交，同步返回 taskId**，AI 选图）
  - select_photo_result（**同步**，查询选图任务状态；SUCCESS 时内存拉取
    resultUrl 解析 goodImages/badImages 并随 result 打日志）
  - classify_addr_list（**同步**，地点相册列表）
  - classify_addr_file_list（**同步**，地点相册内图片）
  - classify_person_list（**同步**，人物相册列表）
  - classify_person_file_list（**同步**，人物相册内图片）
  - classify_thing_list（**同步**，事物相册列表）
  - classify_thing_file_list（**同步**，事物相册内图片）
  - photo_customization_list（**同步**，自定义相册列表）
  - photo_customization_file_list（**同步**，自定义相册内图片）
  - photo_customization_add（**同步**，创建自定义相册）
  - photo_customization_file_add（**同步**，自定义相册添加文件）
  - photo_customization_update（**同步**，更新自定义相册）
  - story_memory_list（**同步**，故事相册列表）
  - story_memory_file_list（**同步**，故事相册内图片）
  - story_memory_add（**同步**，创建故事相册）
  - story_memory_update（**同步**，更新故事相册）
  - story_memory_playlist_add（**同步**，故事相册播放列表添加文件）
  - album_share_get_info（**同步**，获取相册分享信息；KNOWN GAP：需扩展
    mclaw.api.auth 暴露 get_album_share_header 才能用于生产）
  - search_ai_story（**同步**，搜索 AI 故事相册）
"""

from mclaw.api.registry import ApiRegistry

#: 本子包自治注册表
album_api_registry = ApiRegistry(name='album')

# 触发本子包内所有叶子注册（副作用：@album_api_registry.register 装饰器执行）。
from . import image_deduplicate_api  # noqa: F401
from . import image_batch_deduplicate_api  # noqa: F401
from . import select_image_api  # noqa: F401
from . import classify_addr_list_api  # noqa: F401
from . import classify_addr_file_list_api  # noqa: F401
from . import classify_person_list_api  # noqa: F401
from . import classify_person_file_list_api  # noqa: F401
from . import classify_thing_list_api  # noqa: F401
from . import classify_thing_file_list_api  # noqa: F401
from . import photo_customization_list_api  # noqa: F401
from . import photo_customization_file_list_api  # noqa: F401
from . import photo_customization_add_api  # noqa: F401
from . import photo_customization_file_add_api  # noqa: F401
from . import photo_customization_update_api  # noqa: F401
from . import story_memory_list_api  # noqa: F401
from . import story_memory_file_list_api  # noqa: F401
from . import story_memory_add_api  # noqa: F401
from . import story_memory_update_api  # noqa: F401
from . import story_memory_playlist_add_api  # noqa: F401
from . import album_share_get_info_api  # noqa: F401
from . import search_ai_story_api  # noqa: F401

__all__ = ['album_api_registry']
