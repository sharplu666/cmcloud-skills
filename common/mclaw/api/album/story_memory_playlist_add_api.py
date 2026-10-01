#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""故事相册播放列表添加文件（同步接口）。

设置指定回忆/故事相册的播放列表——传入的 ``fileIds`` 列表顺序即为播放顺序。
**本接口为同步接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §17（设置回忆/故事播放列表）

前置约束：
  - 用户必须已开启智能相册功能
  - ``albumId`` 为已存在的回忆/故事相册 ID
  - ``fileIds`` 为按播放顺序排列的个人云图片 fileId 列表

响应说明：
  本接口响应为标准信封（``code`` / ``success`` / ``message``），``data`` 含
  ``coverId`` 业务字段（封面文件 ID，接口文档标注为可选返回）。基类
  ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类业务字段
  （带 alias）会被自动填充；但 ``BaseSyncApi._parse_response`` 硬编码用
  基类 ``SyncResponse.from_response`` 解析，识别不了子类，故需重写
  ``_parse_response`` 指向本接口的 ``StoryMemoryPlaylistAddResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.base._ai_space_log import append_ai_space_log


__all__ = [
    'StoryMemoryPlaylistAddRequest',
    'StoryMemoryPlaylistAddResponse',
    'StoryMemoryPlaylistAddApi',
]


class StoryMemoryPlaylistAddRequest(BaseModel):
    """故事相册播放列表添加文件接口入参。

    本接口属于 album 体系（参数为 ``albumId`` + ``fileIds``），与媒体发送型
    同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）
    字段不重合，故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        album_id: 回忆/故事相册 ID
        file_ids: 按播放顺序排列的图片 fileId 列表
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    album_id: str = Field(..., alias='albumId')
    file_ids: List[str] = Field(..., alias='fileIds')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。"""
        return {'albumId': self.album_id, 'fileIds': list(self.file_ids)}


class StoryMemoryPlaylistAddResponse(SyncResponse):
    """故事相册播放列表添加文件接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``cover_id``：封面文件 ID（接口文档标注为可选返回 ``data.coverId``）。
        为防御性处理，默认值为空串。

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故该字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    cover_id: str = Field('', alias='coverId')


@album_api_registry.register('story_memory_playlist_add')
class StoryMemoryPlaylistAddApi(BaseSyncApi):
    """故事相册播放列表添加文件的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/story/memory/playlist/add``，
    请求即返回最终结果（``code`` / ``success`` / ``message`` / ``data.coverId``），
    无 ``taskId`` 轮询。

    Response 字段扩展了 ``cover_id``，与基类 ``SyncResponse`` 不一致，故必须
    类型化 ``execute`` 签名 + 重写 ``_parse_response`` 指向
    ``StoryMemoryPlaylistAddResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/story/memory/playlist/add'

    api_category = 'album'
    api_label = '故事相册播放列表添加文件'

    is_story: bool = True

    def __init__(
        self,
        host: str,
        auth_fn: Any,
        logger: Any = None,
        redact_params: Optional[List[str]] = None,
        ai_space_log_path: Optional[str] = None,
    ) -> None:
        """注入相册端点专用鉴权头。

        覆盖 ``self._auth`` 为 ``get_album_header``（在标准云盘鉴权头基础上
        追加 ``Content-Type`` / ``x-yun-client-info``），对齐 legacy
        ``cm_cloud_http.py`` 的 ``_send_request(header_type='json')`` 链路。
        ``get_album_header`` 每次调用都重读 ``.env``，token 文件更新后
        下次请求即生效。

        Args:
            ai_space_log_path: AI 空间日志文件路径。非空时，``execute`` 成功后
                会向该文件追加一行 ``{"storyId": "<id>", "type": "story"}``，
                用于追踪归档链路。
                默认 ``None``，向后兼容不写日志。
        """
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_album_header
        self._ai_space_log_path = ai_space_log_path or ''

    def execute(
        self,
        request: StoryMemoryPlaylistAddRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        use_ai_space_log: bool = True,
        **kwargs: Any,
    ) -> StoryMemoryPlaylistAddResponse:
        """类型化入口：入参指向 ``StoryMemoryPlaylistAddRequest``，返回
        ``StoryMemoryPlaylistAddResponse``。

        本接口 Request 为 album 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展了 ``cover_id``，均与基类不一致，故必须类型化覆盖 execute
        签名。实际流程通过 ``super().execute`` 转发，响应类型转换由重写的
        ``_parse_response`` 完成。

        Args:
            use_ai_space_log: ``True``（默认）且 ``__init__`` 传入了
                ``ai_space_log_path`` 时，成功响应会追加一行日志。传 ``False``
                跳过日志写入。日志记录的 ``storyId`` 取自 ``request.album_id``
                （API 请求字段名为 ``albumId``，但本接口属回忆故事路径族，
                语义即 ``storyId``）。
        """
        response = super().execute(request, *args, info_dict=info_dict, **kwargs)
        if (
            use_ai_space_log
            and self._ai_space_log_path
            and response.success
        ):
            append_ai_space_log(
                self._ai_space_log_path,
                is_story=self.is_story,
                album_id=request.album_id,
                record_type='story',
                logger=self.logger,
            )
        return response

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> StoryMemoryPlaylistAddResponse:
        """重写基类钩子：用 ``StoryMemoryPlaylistAddResponse.from_response``
        构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``cover_id``）。本方法改用子类
        的 ``from_response``，其内部默认展平 ``data`` 嵌套层后，子类字段按
        alias 自动填充。
        """
        return StoryMemoryPlaylistAddResponse.from_response(raw, trace_id)
