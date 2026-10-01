#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地点相册列表（同步接口）。

按地点聚合查询相册列表，返回所有地点相册及其元信息。**本接口为同步
接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §1

响应说明：
  本接口响应为标准信封 ``{code, success, message, data: {...}}``，业务
  字段（``nextPageCursor`` / ``totalCount`` / ``list``）直接位于 ``data``
  下。基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类
  业务字段（带 alias）会被自动填充，**无需重写 ``from_response``**。
  但 ``BaseSyncApi._parse_response`` 硬编码用基类 ``SyncResponse.from_response``
  解析，识别不了子类，故需重写 ``_parse_response`` 指向本接口的
  ``ClassifyAddrListResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.album._models import AlbumListItem, PageInfo


__all__ = [
    'ClassifyAddrListRequest',
    'ClassifyAddrListResponse',
    'ClassifyAddrListApi',
]


class ClassifyAddrListRequest(BaseModel):
    """地点相册列表接口入参。

    本接口属于 cloudId 体系（参数为 ``pageInfo`` / ``areaCodes``），与媒体
    发送型同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/
    sourceTaskId）字段不重合，故直接继承 ``BaseModel``，避免引入无关字段
    污染。

    Attributes:
        page_info: 游标分页信息。
        need_total_count: 是否返回总数：0 不返回，1 返回。默认 1。
        area_codes: 地点编码列表，空或不传表示查全部。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    page_info: PageInfo = Field(..., alias='pageInfo')
    need_total_count: int = Field(1, alias='needTotalCount')
    area_codes: Optional[List[str]] = Field(None, alias='areaCodes')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        ``areaCodes`` 仅在非空时包含——空列表或 None 表示查全部地点。
        """
        payload: Dict[str, Any] = {
            'needTotalCount': self.need_total_count,
            'pageInfo': self.page_info.model_dump(by_alias=True, exclude_none=True),
        }
        if self.area_codes:
            payload['areaCodes'] = list(self.area_codes)
        return payload


class ClassifyAddrListResponse(SyncResponse):
    """地点相册列表接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``next_page_cursor``：下一页游标，最后一页为空串。
      - ``total_count``：相册总数（``needTotalCount=1`` 时返回）。
      - ``list``：相册列表，每项为 ``AlbumListItem``。

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故这些
    字段会被 ``model_validate`` 按 alias 自动填充，**无需重写
    ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    next_page_cursor: str = Field('', alias='nextPageCursor')
    total_count: int = Field(0, alias='totalCount')
    list: List[AlbumListItem] = Field(default_factory=list, alias='list')


@album_api_registry.register('classify_addr_list')
class ClassifyAddrListApi(BaseSyncApi):
    """地点相册列表的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/classify/addr/list``，请求
    即返回最终结果（``nextPageCursor`` / ``totalCount`` / ``list``），
    无 ``taskId`` 轮询。

    Response 字段扩展了 ``next_page_cursor`` / ``total_count`` / ``list``，
    与基类 ``SyncResponse`` 不一致，故必须类型化 ``execute`` 签名 + 重写
    ``_parse_response`` 指向 ``ClassifyAddrListResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/classify/addr/list'

    api_category = 'album'
    api_label = '地点相册列表'

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
        request: ClassifyAddrListRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ClassifyAddrListResponse:
        """类型化入口：入参指向 ``ClassifyAddrListRequest``，返回
        ``ClassifyAddrListResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展了 ``next_page_cursor`` / ``total_count`` / ``list``，均与
        基类不一致，故必须类型化覆盖 execute 签名。实际流程通过
        ``super().execute`` 转发，响应类型转换由重写的 ``_parse_response``
        完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ClassifyAddrListResponse:
        """重写基类钩子：用 ``ClassifyAddrListResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``next_page_cursor`` /
        ``total_count`` / ``list``）。本方法改用子类的 ``from_response``，
        其内部默认展平 ``data`` 嵌套层后，子类字段按 alias 自动填充。
        """
        return ClassifyAddrListResponse.from_response(raw, trace_id)
