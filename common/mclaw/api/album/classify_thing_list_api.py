#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事物相册列表（同步接口）。

按事物标签聚合查询相册列表，返回所有事物相册及其元信息。**本接口为同步
接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §3

响应说明：
  本接口响应 ``data`` 含 ``nextPageCursor`` / ``totalCount`` / ``list`` 业务
  字段，其中 ``list[]`` 项含事物相册特有的 ``labelCode``（事物标签编码）与
  ``subAlbumFlag``（是否有子相册标识）。基类 ``SyncResponse.from_response``
  默认展平 ``data`` 嵌套层，子类业务字段（带 alias）会被自动填充；但
  ``BaseSyncApi._parse_response`` 硬编码用基类 ``SyncResponse.from_response``
  解析，识别不了子类，故需重写 ``_parse_response`` 指向本接口的
  ``ClassifyThingListResponse``。

入参说明：
  §3 文档表格仅列 ``pageInfo``（必填）、``labelCodes``（可选）、``labelScope``
  （可选）三个字段，未列顶层 ``needTotalCount``；``PageInfo`` 已含
  ``need_total_count=1`` 默认值，序列化时会随 ``pageInfo`` 内字段输出，故
  ``to_payload`` 无需再输出顶层 ``needTotalCount``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.album._models import AlbumListItem, PageInfo


__all__ = [
    'ClassifyThingListRequest',
    'ClassifyThingListResponse',
    'ClassifyThingListApi',
]


class ClassifyThingListRequest(BaseModel):
    """事物相册列表接口入参。

    本接口属于 cloudId 体系（参数为 ``pageInfo`` / ``labelCodes`` /
    ``labelScope``），与媒体发送型同步基类 ``SyncRequest``
    （sendType/fileUrl/fileId/imageExt/sourceTaskId）字段不重合，故直接继承
    ``BaseModel``，避免引入无关字段污染。

    Attributes:
        page_info: 分页信息（游标分页）。``PageInfo`` 默认含
            ``need_total_count=1``，序列化时随 ``pageInfo`` 输出
            ``needTotalCount``，无需再在顶层重复声明。
        label_codes: 事物标签编码列表，用于按标签过滤相册；为 None 时不输出
            该字段，服务端按全量事物相册返回。
        label_scope: 标签范围：0=事物标签对应相册（默认），1=小类标签事物
            相册。为 None 时不输出该字段，由服务端按默认 0 处理。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    page_info: PageInfo = Field(..., alias='pageInfo')
    label_codes: Optional[List[str]] = Field(None, alias='labelCodes')
    label_scope: Optional[int] = Field(None, alias='labelScope')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        ``labelCodes`` / ``labelScope`` 仅在非 None 时输出，避免服务端将
        空值误解为「限定空范围」。``pageInfo`` 内的 ``needTotalCount`` 由
        ``PageInfo`` 默认值 1 自动带上，无需在顶层重复声明。
        """
        payload: Dict[str, Any] = {
            'pageInfo': self.page_info.model_dump(
                by_alias=True, exclude_none=True
            ),
        }
        if self.label_codes is not None:
            payload['labelCodes'] = list(self.label_codes)
        if self.label_scope is not None:
            payload['labelScope'] = self.label_scope
        return payload


class ClassifyThingListResponse(SyncResponse):
    """事物相册列表接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``next_page_cursor``：下一页游标，最后一页为空。
      - ``total_count``：相册总数。
      - ``list``：相册列表，项类型 ``AlbumListItem``，含事物相册特有的
        ``labelCode``（事物标签编码）与 ``subAlbumFlag``（是否有子相册标识），
        通过 ``AlbumListItem.label_code`` / ``sub_album_flag`` 暴露。

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故这些字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    next_page_cursor: str = Field('', alias='nextPageCursor')
    total_count: int = Field(0, alias='totalCount')
    list: List[AlbumListItem] = Field(default_factory=list, alias='list')


@album_api_registry.register('classify_thing_list')
class ClassifyThingListApi(BaseSyncApi):
    """事物相册列表的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/classify/thing/list``，请求即
    返回最终结果（``nextPageCursor`` / ``totalCount`` / ``list``），无
    ``taskId`` 轮询。

    Response 字段扩展了 ``next_page_cursor`` / ``total_count`` / ``list``，与
    基类 ``SyncResponse`` 不一致，故必须类型化 ``execute`` 签名 + 重写
    ``_parse_response`` 指向 ``ClassifyThingListResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/classify/thing/list'

    api_category = 'album'
    api_label = '事物相册列表'

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
        request: ClassifyThingListRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ClassifyThingListResponse:
        """类型化入口：入参指向 ``ClassifyThingListRequest``，返回
        ``ClassifyThingListResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
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
    ) -> ClassifyThingListResponse:
        """重写基类钩子：用 ``ClassifyThingListResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``next_page_cursor`` /
        ``total_count`` / ``list``）。本方法改用子类的 ``from_response``，其内部
        默认展平 ``data`` 嵌套层后，子类字段按 alias 自动填充。
        """
        return ClassifyThingListResponse.from_response(raw, trace_id)
