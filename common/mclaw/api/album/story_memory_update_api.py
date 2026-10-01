#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修改回忆/故事相册（同步接口）。

修改回忆/故事相册的信息（标题、副标题、封面、背景音乐）。**本接口为
同步接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §13

前置约束：
  - ``albumId`` 必填，标识要修改的回忆/故事相册
  - 至少指定一个修改项（``name`` / ``secondTitle`` / ``cover`` / ``musicId``）

响应说明：
  本接口响应为标准信封 ``{code, success, message}``，``data`` 内无业务字段。
  基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，本接口
  Response 子类未扩展业务字段，与基类结构一致，**无需重写 ``from_response``**。
  但 ``BaseSyncApi._parse_response`` 硬编码用基类 ``SyncResponse.from_response``
  解析，识别不了子类，故需重写 ``_parse_response`` 指向本接口的
  ``StoryMemoryUpdateResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header


__all__ = [
    'StoryMemoryUpdateRequest',
    'StoryMemoryUpdateResponse',
    'StoryMemoryUpdateApi',
]


class StoryMemoryUpdateRequest(BaseModel):
    """修改回忆/故事相册接口入参。

    本接口属于 cloudId 体系（参数为 ``albumId`` + 可选修改字段），与媒体
    发送型同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/
    sourceTaskId）字段不重合，故直接继承 ``BaseModel``，避免引入无关字段
    污染。

    Attributes:
        album_id: 回忆/故事相册 ID（必填）。
        name: 新标题（可选）。
        second_title: 新副标题（可选）。
        cover: 新封面图片 fileId（可选）。
        music_id: 背景音乐 ID（可选）。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    album_id: str = Field(..., alias='albumId')
    name: Optional[str] = Field(None, alias='name')
    second_title: Optional[str] = Field(None, alias='secondTitle')
    cover: Optional[str] = Field(None, alias='cover')
    music_id: Optional[str] = Field(None, alias='musicId')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名），排除 None 值。

        ``albumId`` 必填总会出现；``name`` / ``secondTitle`` / ``cover`` /
        ``musicId`` 为可选字段，未传时不出现在 payload 中，避免服务端将
        ``null`` 误解为清空字段。
        """
        payload: Dict[str, Any] = {'albumId': self.album_id}
        if self.name is not None:
            payload['name'] = self.name
        if self.second_title is not None:
            payload['secondTitle'] = self.second_title
        if self.cover is not None:
            payload['cover'] = self.cover
        if self.music_id is not None:
            payload['musicId'] = self.music_id
        return payload


class StoryMemoryUpdateResponse(SyncResponse):
    """修改回忆/故事相册接口出参（同步返回）。

    本接口响应 ``data`` 内无业务字段（标准信封 ``{code, success, message}``），
    故 Response 子类未扩展字段，与基类 ``SyncResponse`` 结构一致，
    **无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')


@album_api_registry.register('story_memory_update')
class StoryMemoryUpdateApi(BaseSyncApi):
    """修改回忆/故事相册的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/story/memory/update``，
    请求即返回最终结果（标准信封），无 ``taskId`` 轮询。

    Response 子类虽未扩展业务字段，但 ``BaseSyncApi._parse_response``
    硬编码用基类 ``SyncResponse.from_response`` 解析，识别不了子类，故
    仍需重写 ``_parse_response`` 指向 ``StoryMemoryUpdateResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/story/memory/update'

    api_category = 'album'
    api_label = '更新故事相册'

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
        request: StoryMemoryUpdateRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> StoryMemoryUpdateResponse:
        """类型化入口：入参指向 ``StoryMemoryUpdateRequest``，返回
        ``StoryMemoryUpdateResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类），故必须
        类型化覆盖 execute 签名。实际流程通过 ``super().execute`` 转发，
        响应类型转换由重写的 ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> StoryMemoryUpdateResponse:
        """重写基类钩子：用 ``StoryMemoryUpdateResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口子类。本方法改用子类的 ``from_response``，
        其内部默认展平 ``data`` 嵌套层后按 alias 自动填充（本接口 data 内
        无业务字段，仅信封字段被填充）。
        """
        return StoryMemoryUpdateResponse.from_response(raw, trace_id)
