#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桶（Bucketer）注册中心。

外部扩展
========

新桶可在包外注册 —— ``@register_bucket`` 为全局装饰器，在任意可 import 的模块中
声明即可，无需修改本包：

    from mclaw.api.search_fusion import File
    from mclaw.shared.organize.bucket import (
        Bucketer,
        UNKNOWN_BUCKET,
        register_bucket,
    )

    @register_bucket('make')
    class MakeBucketer(Bucketer):
        def bucket_key(self, f: File) -> str:
            m = f.media_meta_info.make if f.media_meta_info else ''
            return m.strip() if m.strip() else UNKNOWN_BUCKET

在应用入口 ``import bucket_ext  # noqa: F401`` 触发注册后即可使用。

规则：桶名全局唯一；``bucket_key`` 返回 ``str``（单值）或 ``list[str]``（多值）；
缺失值用 ``UNKNOWN_BUCKET`` / ``[UNKNOWN_BUCKET]``。

内置桶
======

导入本包即触发注册。顶层 API：

    from mclaw.shared.organize.bucket import (
        Bucketer,
        UNKNOWN_BUCKET,
        register_bucket,
        BUCKET_REGISTRY,
    )

    时间：    day / week / month / year（优先级链） + takenDay/Week/Month/Year（仅拍摄时间） + uploadDay/Week/Month/Year（仅上传时间） + updateDay/Week/Month/Year（仅更新时间）
    地点：    location / country / province / city / district / township / locationAoi
    多值字段：peopleNameList / relationshipNameList / thingLabelList / objectList
    文件属性：category / fileExtension / livePhoto / faceCount / faceGroup
    特殊：    all（全部归一，不聚类）
"""

from __future__ import annotations

from typing import List, Union

from mclaw.api.search_fusion import File

# ---------------------------------------------------------------------
# 顶层 API
# ---------------------------------------------------------------------

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET  # noqa: F401
from mclaw.shared.organize.bucket.registry import (  # noqa: F401
    register_bucket,
    build_bucket_fn,
    get_bucket_class,
    BUCKET_REGISTRY,
    BucketRegistry,
    BucketCategoryInfo,
)
from mclaw.shared.organize.bucket.time_bucket import (  # noqa: F401
    resolve_time_value,
    TIME_FIELD_PRIORITY,
)
from mclaw.shared.organize.bucket.location_bucket import (  # noqa: F401
    SUPPORTED_LOCATION_FIELDS,
    DEFAULT_LOCATION_FIELD,
)
from mclaw.shared.organize.bucket.set_field_bucket import SUPPORTED_SET_FIELDS  # noqa: F401
from mclaw.shared.organize.bucket.result import (  # noqa: F401
    ClusterResult,
    DEFAULT_SET_THRESHOLD,
    group_by_bucketer,
    distinct_excluding_unknown,
)
from mclaw.shared.organize.bucket.profile import (  # noqa: F401
    cluster_one,
    profile_all_dimensions,
    format_cluster_report,
    format_cross_report,
    format_hierarchical_report,
)


# Trigger registration: importing a submodule runs its @register_bucket decorators.
from mclaw.shared.organize.bucket import time_bucket  # noqa: F401
from mclaw.shared.organize.bucket import location_bucket  # noqa: F401
from mclaw.shared.organize.bucket import location_aoi_bucket  # noqa: F401
from mclaw.shared.organize.bucket import set_field_bucket  # noqa: F401
from mclaw.shared.organize.bucket import category_bucket  # noqa: F401
from mclaw.shared.organize.bucket import file_extension_bucket  # noqa: F401
from mclaw.shared.organize.bucket import live_photo_bucket  # noqa: F401
from mclaw.shared.organize.bucket import face_count_bucket  # noqa: F401
from mclaw.shared.organize.bucket import face_group_bucket  # noqa: F401
from mclaw.shared.organize.bucket import all_bucket  # noqa: F401
from mclaw.shared.organize.bucket.all_bucket import ALL_BUCKET  # noqa: F401

# discovery 层（依赖上述注册完成才能正确解析）
from mclaw.shared.organize.bucket.discovery import (  # noqa: F401
    resolve_dimensions,
    bucket_category_of,
    list_categories,
)

from mclaw.shared.organize.bucket.cli_help import (  # noqa: F401
    HELP_MANAGE_CLUSTER_BUCKET,
    HELP_ORGANIZE_BUCKET_SINGLE_ARCHIVE,
    HELP_ORGANIZE_BUCKET_SINGLE_MEMORY,
    HELP_ORGANIZE_BUCKET_SINGLE_PLAN,
    HELP_ORGANIZE_BUCKET_SINGLE_PRESEARCH,
    HELP_ORGANIZE_BUCKETS,
    HELP_ORGANIZE_MODE,
    REGISTERED_BUCKET_NAMES,
)


__all__ = [
    # 基类与常量
    'Bucketer',
    'UNKNOWN_BUCKET',
    'ALL_BUCKET',
    # 注册表
    'register_bucket',
    'build_bucket_fn',
    'get_bucket_class',
    'BUCKET_REGISTRY',
    'BucketRegistry',
    'BucketCategoryInfo',
    # discovery 层
    'resolve_dimensions',
    'bucket_category_of',
    'list_categories',
    # 时间与地点常量
    'resolve_time_value',
    'TIME_FIELD_PRIORITY',
    'SUPPORTED_LOCATION_FIELDS',
    'DEFAULT_LOCATION_FIELD',
    'SUPPORTED_SET_FIELDS',
    # 聚类与画像
    'ClusterResult',
    'DEFAULT_SET_THRESHOLD',
    'group_by_bucketer',
    'distinct_excluding_unknown',
    'cluster_one',
    'profile_all_dimensions',
    'format_cluster_report',
    'format_cross_report',
    'format_hierarchical_report',
    # CLI help（注册完成后派生）
    'HELP_MANAGE_CLUSTER_BUCKET',
    'HELP_ORGANIZE_BUCKET_SINGLE_ARCHIVE',
    'HELP_ORGANIZE_BUCKET_SINGLE_MEMORY',
    'HELP_ORGANIZE_BUCKET_SINGLE_PLAN',
    'HELP_ORGANIZE_BUCKET_SINGLE_PRESEARCH',
    'HELP_ORGANIZE_BUCKETS',
    'HELP_ORGANIZE_MODE',
    'REGISTERED_BUCKET_NAMES',
]
