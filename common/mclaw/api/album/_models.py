#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""album 共享 BaseModel（Pydantic v2）。

被 `mclaw/api/album/` 下各叶子 api 模块复用的入参/出参子结构。本模块**不定义
Request/Response/Api 子类**，只放业务结构 BaseModel，对齐 `personal_saas/_models.py`
与 `search_fusion/_models.py` 的共享子模型模式。

字段命名：Python 用 snake_case，``Field(alias=...)`` 映射 API 驼峰字段名。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    # 入参子结构
    'PageInfo',
    'ShowInfo',
    'PhotoItem',
    # 出参子结构
    'AlbumListItem',
    'FileInfo',
]


# 公共 ConfigDict：populate_by_name + 忽略服务端新增字段
_MODEL_CONFIG = ConfigDict(populate_by_name=True, extra='ignore')


# ──────────────────────────── 入参子结构 ────────────────────────────


class PageInfo(BaseModel):
    """游标分页信息（§1-§11、§16 大多数列表接口使用）。

    字段对应接口文档 ``pageInfo`` 对象：
      - ``pageCursor``：起始游标，空串从第一页开始
      - ``pageSize``：每页条数，默认 10
      - ``needTotalCount``：0 不返回总数，1 返回
    """

    model_config = _MODEL_CONFIG

    page_cursor: str = Field('', alias='pageCursor')
    page_size: int = Field(10, alias='pageSize')
    need_total_count: int = Field(1, alias='needTotalCount')


class ShowInfo(BaseModel):
    """范围分页信息（仅 §24 SearchAIStory 使用）。

    与 ``PageInfo`` 的游标分页不同——``showInfo`` 用 ``startNum`` / ``stopNum``
    表示查询区间（闭区间，从 1 开始）。
    """

    model_config = _MODEL_CONFIG

    start_num: int = Field(1, alias='startNum')
    stop_num: int = Field(10, alias='stopNum')


class PhotoItem(BaseModel):
    """分享接口（§23 getAlbumShareInfo）``photos`` 数组项。

    由 ``content_ids: List[str]`` 在 Request ``to_payload`` 中按顺序映射而来：
    ``sort`` 从 1 开始递增，``contentID`` 取自传入的 fileId。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    sort: int
    content_id: str = Field(..., alias='contentID')


# ──────────────────────────── 出参子结构 ────────────────────────────


class AlbumListItem(BaseModel):
    """通用相册列表项。

    覆盖 §1 地点相册、§2 人物相册、§3 事物相册、§4 自定义相册、§10 故事相册
    列表响应 ``data.list[]`` 的并集字段。各接口特有字段（如人物相册的
    ``staticFile``、事物相册的 ``labelCode``/``subAlbumFlag``）以 Optional 暴露，
    ``extra='ignore'`` 容忍未返回字段。
    """

    model_config = _MODEL_CONFIG

    id: str = ''
    name: str = ''
    # type 服务端可能返回 int（如故事相册 6/8）或 str（如 'addr'/'person'），故联合类型
    type: Union[str, int] = ''
    # cover 故事相册列表返回的是封面对象 {fileId, addressDetail,...}，自定义相册返回 URL 字符串
    cover: Union[str, Dict[str, Any]] = ''
    description: str = ''
    file_number: int = Field(0, alias='fileNumber')
    update_time: str = Field('', alias='updateTime')
    create_time: str = Field('', alias='createTime')
    area_code: str = Field('', alias='areaCode')
    # §2 人物相册特有
    static_file: Optional[Dict[str, Any]] = Field(None, alias='staticFile')
    # §3 事物相册特有
    label_code: str = Field('', alias='labelCode')
    sub_album_flag: int = Field(0, alias='subAlbumFlag')


class FileInfo(BaseModel):
    """标准文件信息对象。

    对应 §5/§6/§7/§11 ``data.list[].fileInfo``（或 §8 ``data.list[]`` 直接项）
    的标准文件结构。``extra='ignore'`` 容忍服务端新增字段（如缩略图 URL 列表）。
    """

    model_config = _MODEL_CONFIG

    file_id: str = Field('', alias='fileId')
    name: str = ''
    size: int = 0
    category: str = ''
    created_at: str = Field('', alias='createdAt')
    updated_at: str = Field('', alias='updatedAt')
    name_path: str = Field('', alias='namePath')
    file_extension: str = Field('', alias='fileExtension')
    address_detail: Optional[Dict[str, Any]] = Field(None, alias='addressDetail')
    user_tags: Optional[List[Any]] = Field(None, alias='userTags')
