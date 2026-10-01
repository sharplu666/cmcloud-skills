#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义相册列表（同步接口）。

查询用户手工创建的全部自定义相册列表。**本接口为同步接口**——请求即返回
最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §4（自定义相册列表）

前置约束：
  - 用户必须已开启智能相册功能

入参说明：
  - ``imageThumbnailStyleList``（必填，String[]）：缩略图样式，可选值
    ``Small`` / ``Middle`` / ``Big`` / ``Large``，默认 ``["Big"]``
  - ``pageInfo``（必填，Object）：游标分页信息，详见 ``_models.PageInfo``

响应说明：
  本接口响应 ``data`` 含 ``nextPageCursor`` / ``totalCount`` / ``list`` 业务字段。
  基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类业务字段
  （带 alias）会被自动填充；但 ``BaseSyncApi._parse_response`` 硬编码用
  基类 ``SyncResponse.from_response`` 解析，识别不了子类，故需重写
  ``_parse_response`` 指向本接口的 ``PhotoCustomizationListResponse``。

  注意：§4 文档表格未列顶层 ``needTotalCount`` 字段，故 ``to_payload`` 不输出
  顶层 ``needTotalCount``（``PageInfo`` 已含 ``need_total_count=1`` 默认，会随
  ``pageInfo`` 一起序列化到 payload）。legacy ``api_photo_customization_list``
  写了顶层 ``needTotalCount=1``，但文档§4 未列——这里以文档为准，不输出顶层
  ``needTotalCount``。若需严格对齐 legacy，可在 Request 上加顶层字段。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.album._models import AlbumListItem, PageInfo


__all__ = [
    'PhotoCustomizationListRequest',
    'PhotoCustomizationListResponse',
    'PhotoCustomizationListApi',
]


class PhotoCustomizationListRequest(BaseModel):
    """自定义相册列表接口入参。

    本接口属于 album 体系（参数为 ``imageThumbnailStyleList`` + ``pageInfo``），
    与媒体发送型同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/
    sourceTaskId）字段不重合，故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        page_info: 游标分页信息（``PageInfo``），含 ``pageCursor`` / ``pageSize``
            / ``needTotalCount``，``needTotalCount`` 默认 1（随 pageInfo 一起
            序列化到 payload，不在顶层输出）。
        image_thumbnail_style_list: 缩略图样式列表，可选值 ``Small`` / ``Middle``
            / ``Big`` / ``Large``，默认 ``["Big"]``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    page_info: PageInfo = Field(..., alias='pageInfo')
    image_thumbnail_style_list: List[str] = Field(
        default_factory=lambda: ['Big'], alias='imageThumbnailStyleList'
    )

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        按文档§4 字段表，顶层只输出 ``imageThumbnailStyleList`` 与 ``pageInfo``；
        ``needTotalCount`` 仅在 ``pageInfo`` 内（``PageInfo`` 默认 1），
        不在顶层输出，以文档为准。
        """
        return {
            'imageThumbnailStyleList': list(self.image_thumbnail_style_list),
            'pageInfo': self.page_info.model_dump(by_alias=True, exclude_none=True),
        }


class PhotoCustomizationListResponse(SyncResponse):
    """自定义相册列表接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``next_page_cursor``：下一页游标，最后一页为空串
      - ``total_count``：相册总数
      - ``list``：自定义相册列表，每项为 ``AlbumListItem``（字段同通用相册结构）

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故这些字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    next_page_cursor: str = Field('', alias='nextPageCursor')
    total_count: int = Field(0, alias='totalCount')
    list: List[AlbumListItem] = Field(default_factory=list, alias='list')


@album_api_registry.register('photo_customization_list')
class PhotoCustomizationListApi(BaseSyncApi):
    """自定义相册列表的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/photo/customization/list``，
    请求即返回最终结果（``nextPageCursor`` / ``totalCount`` / ``list``），
    无 ``taskId`` 轮询。

    Response 字段扩展了 ``next_page_cursor`` / ``total_count`` / ``list``，
    与基类 ``SyncResponse`` 不一致，故必须类型化 ``execute`` 签名 + 重写
    ``_parse_response`` 指向 ``PhotoCustomizationListResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/photo/customization/list'

    api_category = 'album'
    api_label = '自定义相册列表'

    def __init__(
        self,
        host: str,
        auth_fn: Any,
        logger: Any = None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        """注入相册端点专用鉴权头。

        覆盖 ``self._auth`` 为 ``get_album_header``（在标准云盘鉴权头基础上
        追加 ``Content-Type`` / ``x-yun-client-info``），对齐 legacy
        ``cm_cloud_http.py`` 的 ``_send_request(header_type='json')`` 链路。
        ``get_album_header`` 每次调用都重读 ``.env``，token 文件更新后
        下次请求即生效。
        """
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_album_header

    def execute(
        self,
        request: PhotoCustomizationListRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PhotoCustomizationListResponse:
        """类型化入口：入参指向 ``PhotoCustomizationListRequest``，返回
        ``PhotoCustomizationListResponse``。

        本接口 Request 为 album 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展了 ``next_page_cursor`` / ``total_count`` / ``list``，均与基类
        不一致，故必须类型化覆盖 execute 签名。实际流程通过 ``super().execute``
        转发，响应类型转换由重写的 ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> PhotoCustomizationListResponse:
        """重写基类钩子：用 ``PhotoCustomizationListResponse.from_response``
        构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``next_page_cursor`` /
        ``total_count`` / ``list``）。本方法改用子类的 ``from_response``，其内部
        默认展平 ``data`` 嵌套层后，子类字段按 alias 自动填充。
        """
        return PhotoCustomizationListResponse.from_response(raw, trace_id)
