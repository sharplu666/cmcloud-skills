#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_tool —— AI 图片处理类 API（自治 registry 模式）。

本子包 owns 自己的 ``image_tool_api_registry``。
所有叶子 API 装饰器指向它。
顶层 ``ApiDispatcher`` 联邦本 registry 后即可通过
``d.image_tool.<leaf>(req)`` 或 ``d.execute('image_tool.<leaf>', req)`` 调用。

已注册叶子（15 项，2 项同步）：
  - ai_avatar / ai_expand_image / ai_image_generate / ai_retouch /
    baby_face_prediction / baby_time_machine / human_matting / image_caption /
    image_comic_style / image_enhance / image_shift（**同步**）/ live_photo /
    old_photo_restore / text_to_image
  - ai_portrait_face_detect（**同步**，AI 写真人脸检测）
"""

from mclaw.api.registry import ApiRegistry

#: 本子包自治注册表
image_tool_api_registry = ApiRegistry(name='image_tool')

# 触发本子包内所有叶子注册（副作用：@image_tool_api_registry.register 装饰器执行）。
from . import ai_avatar_api  # noqa: F401
from . import ai_expand_image_api  # noqa: F401
from . import ai_image_generate_api  # noqa: F401
from . import ai_portrait_face_detect_api  # noqa: F401
from . import ai_retouch_api  # noqa: F401
from . import baby_face_prediction_api  # noqa: F401
from . import baby_time_machine_api  # noqa: F401
from . import human_matting_api  # noqa: F401
from . import image_caption_api  # noqa: F401
from . import image_comic_style_api  # noqa: F401
from . import image_enhance_api  # noqa: F401
from . import image_shift_api  # noqa: F401
from . import live_photo_api  # noqa: F401
from . import old_photo_restore_api  # noqa: F401
from . import text_to_image_api  # noqa: F401

__all__ = ['image_tool_api_registry']
