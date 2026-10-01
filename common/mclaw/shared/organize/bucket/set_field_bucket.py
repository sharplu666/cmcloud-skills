#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多值 set 字段桶。

参考 ``File.ai_analysis_info`` 中的 4 个多值字段：

    - ``people_name_list``：人名列表（源 API ``peopleNameList``）
    - ``relationship_name_list``：关系列表（源 API ``relationshipNameList``）
    - ``thing_label_list``：事物标签列表（取 ``.name``，源 API ``thingLabelList``）
    - ``object_list``：地标/名人列表（源 API ``objectList``）

特性：
    - 一个 ``File`` 可同时进入多个桶（如 ``thingLabelList=["天空","海"]`` 进两桶）
    - 空值/全白色 → 进 ``['UNKNOWN']`` 单元素桶
    - ``is_multi_value = True`` 标记，供调用方 introspection

桶名沿用源 API camelCase 字段名（``peopleNameList`` 等），与原 dataclass 版本
保持调用方兼容；内部读取走 snake_case Pydantic 属性。
"""

from __future__ import annotations

from typing import Callable, List

from mclaw.api.search_fusion import File

from mclaw.shared.organize.bucket.base import Bucketer, UNKNOWN_BUCKET
from mclaw.shared.organize.bucket.registry import register_bucket


#: set 字段名（源 API camelCase，作为桶名与 ``field`` 标识） → 取值函数
#: 取值函数输入 ``File``，输出原始 ``list[str]``；空 ``ai_analysis_info`` 时返回 ``[]``。
_SET_FIELD_EXTRACTORS: dict[str, Callable[[File], List[str]]] = {
    'peopleNameList': lambda f: list(f.ai_analysis_info.people_name_list) if f.ai_analysis_info else [],
    'relationshipNameList': lambda f: list(f.ai_analysis_info.relationship_name_list) if f.ai_analysis_info else [],
    'thingLabelList': lambda f: [lbl.name for lbl in f.ai_analysis_info.thing_label_list if lbl.name] if f.ai_analysis_info else [],
    'objectList': lambda f: [s for s in f.ai_analysis_info.object_list if s] if f.ai_analysis_info else [],
}

#: 本模块支持的 set 字段名
SUPPORTED_SET_FIELDS: tuple[str, ...] = tuple(_SET_FIELD_EXTRACTORS.keys())


class _SetFieldBase(Bucketer):
    """多值字段桶基类。

    子类只需覆盖 ``field`` 类属性并 ``@register_bucket``。
    """

    is_multi_value: bool = True
    field: str = ''

    def bucket_key(self, f: File) -> List[str]:
        ai = f.ai_analysis_info
        if ai is None:
            return [UNKNOWN_BUCKET]
        extractor = _SET_FIELD_EXTRACTORS[self.field]
        raw = extractor(f)
        cleaned = [str(x).strip() for x in raw if isinstance(x, (str,)) and str(x).strip()]
        return cleaned or [UNKNOWN_BUCKET]


@register_bucket('peopleNameList')
class PeopleNameListBucketer(_SetFieldBase):
    """按人名分桶（多值）。"""

    bucket_category = 'set'
    bucket_label = '人名'

    field = 'peopleNameList'


@register_bucket('relationshipNameList')
class RelationshipNameListBucketer(_SetFieldBase):
    """按关系分桶（多值）。"""

    bucket_category = 'set'
    bucket_label = '关系'

    field = 'relationshipNameList'


@register_bucket('thingLabelList')
class ThingLabelListBucketer(_SetFieldBase):
    """按事物标签分桶（多值）。"""

    bucket_category = 'set'
    bucket_label = '事物标签'

    field = 'thingLabelList'


@register_bucket('objectList')
class ObjectListBucketer(_SetFieldBase):
    """按地标/名人分桶（多值）。"""

    bucket_category = 'set'
    bucket_label = '地标/名人'

    field = 'objectList'
