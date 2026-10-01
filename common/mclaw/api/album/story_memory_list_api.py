#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回忆/故事相册列表（同步接口）。

查询回忆/故事相册列表，支持按类型筛选（精选相册、时光相册、推荐相册）。
**本接口为同步接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §10

响应说明：
  本接口响应 ``data`` 含 ``nextPageCursor`` / ``totalCount`` / ``list`` 业务
  字段。基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类
  业务字段（带 alias）会被自动填充；但 ``BaseSyncApi._parse_response`` 硬编码
  用基类 ``SyncResponse.from_response`` 解析，识别不了子类，故需重写
  ``_parse_response`` 指向本接口的 ``StoryMemoryListResponse``。

入参说明：
  ``needTotalCount`` 在顶层（不在 ``pageInfo`` 内），``to_payload`` 显式从
  ``pageInfo`` 序列化结果中移除该字段以对齐接口文档与 legacy 脚本。
  ``imageThumbnailStyleList`` 必填，默认 ``['Small']``。``type`` 可选，
  4=精选/5=时光/7=推荐，不传返回全部。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.album._models import AlbumListItem, PageInfo


__all__ = [
    'StoryMemoryListRequest',
    'StoryMemoryListResponse',
    'StoryMemoryListApi',
]


class StoryMemoryListRequest(BaseModel):
    """回忆/故事相册列表接口入参。

    本接口属于 cloudId 体系（参数为 ``pageInfo`` / ``type`` /
    ``imageThumbnailStyleList``），与媒体发送型同步基类 ``SyncRequest``
    （sendType/fileUrl/fileId/imageExt/sourceTaskId）字段不重合，故直接继承
    ``BaseModel``，避免引入无关字段污染。

    Attributes:
        page_info: 分页信息（游标分页）。本接口的 ``needTotalCount`` 在顶层，
            ``to_payload`` 会从 ``pageInfo`` 序列化结果中移除该字段。
        need_total_count: 是否返回总数：0 不返回，1 返回。脚本默认 1。
            对齐 legacy ``api_story_memory_list`` 写死 ``needTotalCount=1``。
        image_thumbnail_style_list: 缩略图配置，默认 ``['Small']``。
        type: 故事类型：4=精选相册，5=时光相册，7=推荐相册；为 None 时不输出
            该字段，服务端返回全部类型。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    page_info: PageInfo = Field(..., alias='pageInfo')
    need_total_count: int = Field(1, alias='needTotalCount')
    image_thumbnail_style_list: List[str] = Field(
        default_factory=lambda: ['Small'], alias='imageThumbnailStyleList'
    )
    type: Optional[int] = Field(None, alias='type')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        ``needTotalCount`` 在顶层（不在 ``pageInfo`` 内），故从 ``pageInfo``
        序列化结果中显式移除该字段，对齐接口文档 §10 demo 与 legacy 脚本
        ``api_story_memory_list``。``type`` 仅在非 None 时输出。
        """
        page_info = self.page_info.model_dump(by_alias=True, exclude_none=True)
        # 本接口 needTotalCount 在顶层，pageInfo 内不重复输出
        page_info.pop('needTotalCount', None)
        payload: Dict[str, Any] = {
            'needTotalCount': self.need_total_count,
            'imageThumbnailStyleList': list(self.image_thumbnail_style_list),
            'pageInfo': page_info,
        }
        if self.type is not None:
            payload['type'] = self.type
        return payload


class StoryMemoryListResponse(SyncResponse):
    """回忆/故事相册列表接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``next_page_cursor``：下一页游标，最后一页为空。
      - ``total_count``：相册总数。
      - ``list``：相册列表，项类型 ``AlbumListItem``，含 ``id`` / ``name`` /
        ``updateTime`` / ``createTime`` 等字段。

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故这些字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    next_page_cursor: str = Field('', alias='nextPageCursor')
    total_count: int = Field(0, alias='totalCount')
    list: List[AlbumListItem] = Field(default_factory=list, alias='list')


@album_api_registry.register('story_memory_list')
class StoryMemoryListApi(BaseSyncApi):
    """回忆/故事相册列表的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/story/memory/list``，请求即
    返回最终结果（``nextPageCursor`` / ``totalCount`` / ``list``），无
    ``taskId`` 轮询。

    Response 字段扩展了 ``next_page_cursor`` / ``total_count`` / ``list``，与
    基类 ``SyncResponse`` 不一致，故必须类型化 ``execute`` 签名 + 重写
    ``_parse_response`` 指向 ``StoryMemoryListResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/story/memory/list'

    api_category = 'album'
    api_label = '回忆/故事相册列表'

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
        request: StoryMemoryListRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> StoryMemoryListResponse:
        """类型化入口：入参指向 ``StoryMemoryListRequest``，返回
        ``StoryMemoryListResponse``。

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
    ) -> StoryMemoryListResponse:
        """重写基类钩子：用 ``StoryMemoryListResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``next_page_cursor`` /
        ``total_count`` / ``list``）。本方法改用子类的 ``from_response``，其内部
        默认展平 ``data`` 嵌套层后，子类字段按 alias 自动填充。
        """
        return StoryMemoryListResponse.from_response(raw, trace_id)
