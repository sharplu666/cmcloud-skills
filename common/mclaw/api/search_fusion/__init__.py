#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_fusion —— 个人云管理类 API（自治 registry 模式）。

本子包 owns 自己的 ``search_fusion_api_registry``，所有叶子 API 装饰器指向它。
顶层 ``ApiDispatcher`` 联邦本 registry 后即可通过 ``d.search_fusion.<leaf>(req)``
或 ``d.execute('search_fusion.<leaf>', req)`` 调用。

已注册叶子：
  - search_merge_file_api      → search_merge_file
  - search_merge_image_api     → search_merge_image
  - search_face_recognize_api  → search_face_recognize
  - search_by_fileId           → search_by_fileId（个人云图片类整合AI信息，mock 兜底）
"""

from mclaw.api.registry import ApiRegistry

#: 本子包自治注册表
search_fusion_api_registry = ApiRegistry(name='search_fusion')

from . import search_merge_file_api  # noqa: F401  副作用：注册
from . import search_merge_image_api  # noqa: F401  副作用：注册
from . import search_face_recognize_api  # noqa: F401  副作用：注册
from . import search_by_fileId  # noqa: F401  副作用：注册

# 业务结构（Pydantic v2 BaseModel）顶层 re-export。
# 调用方应通过 ``from mclaw.api.search_fusion import File`` 等方式访问，
# 避免直接 ``from mclaw.api.search_fusion._models import ...`` 触发
# pyright reportPrivateImportUsage / 受保护成员告警。
from mclaw.api.search_fusion._models import (  # noqa: F401
    AmbiguityItem,
    AddressDetail,
    AiAnalysisInfo,
    FaceInfo,
    FaceRecognizeSelectFaceItem,
    File,
    FileSizeRage,
    FileTimeRange,
    ImageQuality,
    LabelInfo,
    LocationAoi,
    MediaMetaInfo,
    MediaPreviewInfo,
    MergePageInfo,
    RecognizeFaceInfo,
    SearchFileDynamicParam,
    SearchFileParamV3,
    SelectFaceItem,
    SortRange,
    Tag,
    ThumbnailInfo,
)

__all__ = [
    'search_fusion_api_registry',
    # 业务结构
    'AmbiguityItem',
    'AddressDetail',
    'AiAnalysisInfo',
    'FaceInfo',
    'FaceRecognizeSelectFaceItem',
    'File',
    'FileSizeRage',
    'FileTimeRange',
    'ImageQuality',
    'LabelInfo',
    'LocationAoi',
    'MediaMetaInfo',
    'MediaPreviewInfo',
    'MergePageInfo',
    'RecognizeFaceInfo',
    'SearchFileDynamicParam',
    'SearchFileParamV3',
    'SelectFaceItem',
    'SortRange',
    'Tag',
    'ThumbnailInfo',
]
