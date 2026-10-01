#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桶 key 提取器原子类。

所有具体桶（``TimeBucketer`` / ``CityBucketer`` / ``SetFieldBucketer`` …）
继承 ``Bucketer``，实现 ``bucket_key`` 即可被注册表发现。

设计：
    - 桶只负责「从 ``File`` 提取 str | list[str]」一件事
    - 单值字段返回 ``str``（一个 file 进一个桶）
    - 多值字段返回 ``list[str]``（一个 file 可同时进多个桶）
    - 缺失值统一返回 ``UNKNOWN_BUCKET``（单值）或 ``['UNKNOWN']``（多值）
    - 不修改 ``File``（Pydantic v2 模型默认可变，但桶只读不写）
    - ``Bucketer`` 实例可调用：``bucketer(file)`` 委托到 ``bucketer.bucket_key(file)``。

``File`` 来自 ``mclaw.api.search_fusion._models``（Pydantic v2 BaseModel），
字段名为 snake_case（``media_meta_info`` / ``address_detail`` / ``ai_analysis_info`` …），
调用方可 ``File.model_validate(d)`` 由服务端 camelCase 字典构造。
权威来源：``dev/docs/api/cm_cloud_search_fusion.md`` File 结构。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Union

from mclaw.api.search_fusion import File


UNKNOWN_BUCKET: str = 'UNKNOWN'
"""缺失维度的统一桶名。单值桶返回此字符串，多值桶返回 ``[UNKNOWN_BUCKET]``。"""


class Bucketer(ABC):
    """桶 key 提取器原子类。

    子类只需：
        1. 用 ``@register_bucket('your_name')`` 装饰（见 ``registry.py``）
        2. 实现 ``bucket_key`` 方法
        3. 多值字段把 ``is_multi_value`` 置 ``True``（仅用于元信息，不影响算法）
        4. 声明分类元数据（``bucket_category`` / ``bucket_label`` 等），
           供 ``BUCKET_REGISTRY.categories()`` 派生分类视图，支持多维度解析
           （见 ``discovery.resolve_dimensions``）

    示例::

        @register_bucket('province')
        class ProvinceBucketer(Bucketer):
            bucket_category = 'location'
            bucket_label = '省份'

            def bucket_key(self, f: File) -> str:
                p = f.address_detail.province if f.address_detail else ''
                return p.strip() if p.strip() else UNKNOWN_BUCKET
    """

    is_multi_value: bool = False
    """是否多值桶。单值（如 city/time）保持 False；set 字段（如 thingLabelList）置 True。
    取值依据：``File.ai_analysis_info`` 中是否为 ``List`` 类型字段。
    """

    bucket_category: str = 'misc'
    """桶所属分类名。如 ``'time'`` / ``'location'`` / ``'set'`` / ``'attr'`` / ``'device'``。
    取值依据：人为划分的语义分组，由桶作者在定义时声明；缺省 ``'misc'`` 表示未分类。
    用途：``BUCKET_REGISTRY.categories()`` 据此聚合派生分类视图，
    ``discovery.resolve_dimensions(['time', 'location'])`` 据此解析为具体桶名。
    命名加 ``bucket_`` 前缀以避免与 ``File.category``（文件分类：image/video/...）混淆。
    """

    bucket_label: str = ''
    """桶的中文展示标签。如 ``'月'`` / ``'城市'`` / ``'设备品牌'``。
    取值依据：桶作者定义；缺省空串时 ``categories()`` 回退使用 ``bucket_category`` 名。
    用途：UI 展示「可选维度」时用，不参与算法逻辑。
    """

    is_default_in_bucket_category: bool = False
    """是否为所属分类的默认桶。每个分类最多一个桶置 ``True``。
    取值依据：桶作者声明该分类下"最常用"的粒度（如 ``'time'`` 分类默认 ``'month'``）。
    用途：``resolve_dimensions(['time'])`` 不指定具体粒度时取此默认桶；
    缺省 ``False`` 表示非默认，分类整体无默认时 ``resolve_dimensions`` 会要求显式指定。
    """

    applicable_file_categories: tuple[str, ...] = ()
    """该桶适用的 ``File.category`` 取值白名单。
    取值依据：``File.category`` 字段的合法枚举，
    如 ``('image',)`` 表示仅图片有意义，``('image', 'video')`` 表示媒体文件。
    缺省空元组表示对所有文件类型生效（无限制）。
    用途：调用方可据此预筛 ``mgr.all_files``（如 livePhoto 桶仅保留 image），
    避免无关文件污染桶；**提示性而非强制**，不过滤也能跑（只是 UNKNOWN 会多）。
    注意：此字段指的是 ``File.category``（文件分类），**不是** ``bucket_category``，
    故命名不加 ``bucket_`` 前缀。
    """

    @abstractmethod
    def bucket_key(self, file_: File) -> Union[str, List[str]]:
        """从 ``File`` 提取桶 key。

        - 单值桶返回 ``str``
        - 多值桶返回 ``list[str]``，允许同一 file 进多个桶
        - 缺失值：单值返回 ``UNKNOWN_BUCKET``，多值返回 ``[UNKNOWN_BUCKET]``
        """
        raise NotImplementedError

    def __call__(self, file_: File) -> Union[str, List[str]]:
        """让实例可以直接当函数用：``bucketer(f)`` 等价于 ``bucketer.bucket_key(f)``。

        这样 ``QualitySelector.select_top_n_per_bucket`` 等接收 ``Callable[[File], ...]``
        的旧 API 无需改动，传 ``Bucketer`` 实例即可。
        """
        return self.bucket_key(file_)
