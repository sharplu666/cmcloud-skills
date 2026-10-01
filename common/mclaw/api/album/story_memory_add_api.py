#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新建回忆/故事相册（同步接口）。

手工新建一个回忆/故事相册，指定标题、副标题、封面和初始图片，返回新相册 ID。
**本接口为同步接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §12

响应说明：
  本接口响应为标准信封 ``{code, success, message, data: {id}}``，业务
  字段 ``id``（新建相册 ID）直接位于 ``data`` 下。基类
  ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类业务字段
  （带 alias）会被自动填充，**无需重写 ``from_response``**。但
  ``BaseSyncApi._parse_response`` 硬编码用基类 ``SyncResponse.from_response``
  解析，识别不了子类，故需重写 ``_parse_response`` 指向本接口的
  ``StoryMemoryAddResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.base._ai_space_log import append_ai_space_log


__all__ = [
    'StoryMemoryAddRequest',
    'StoryMemoryAddResponse',
    'StoryMemoryAddApi',
]


class StoryMemoryAddRequest(BaseModel):
    """新建回忆/故事相册接口入参。

    本接口属于 cloudId 体系（参数为 ``name`` / ``secondTitle`` / ``cover``
    / ``fileIds``），与媒体发送型同步基类 ``SyncRequest``
    （sendType/fileUrl/fileId/imageExt/sourceTaskId）字段不重合，故直接
    继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        name: 相册标题。
        second_title: 相册副标题。
        cover: 封面图片 fileId。
        file_ids: 图片 fileId 列表。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    name: str = Field(..., alias='name')
    second_title: str = Field(..., alias='secondTitle')
    cover: str = Field(..., alias='cover')
    file_ids: List[str] = Field(..., alias='fileIds')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。"""
        return {
            'name': self.name,
            'secondTitle': self.second_title,
            'cover': self.cover,
            'fileIds': list(self.file_ids),
        }


class StoryMemoryAddResponse(SyncResponse):
    """新建回忆/故事相册接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``id``：新建的相册 ID。接口文档标注为 String，实际成功响应中总会
        返回；为防御性处理，默认值为空串。

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故该字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    id: str = Field('', alias='id')


@album_api_registry.register('story_memory_add')
class StoryMemoryAddApi(BaseSyncApi):
    """新建回忆/故事相册的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/story/memory/add``，
    请求即返回最终结果（``id``），无 ``taskId`` 轮询。

    Response 字段扩展了 ``id``，与基类 ``SyncResponse`` 不一致，故必须
    类型化 ``execute`` 签名 + 重写 ``_parse_response`` 指向
    ``StoryMemoryAddResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/story/memory/add'

    api_category = 'album'
    api_label = '创建故事相册'

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
                会向该文件追加一行
                ``{"storyId": "<id>", "storyName": "<name>", "type": "story"}``，
                用于追踪归档链路。
                默认 ``None``，向后兼容不写日志。
        """
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_album_header
        self._ai_space_log_path = ai_space_log_path or ''

    def execute(
        self,
        request: StoryMemoryAddRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        use_ai_space_log: bool = True,
        **kwargs: Any,
    ) -> StoryMemoryAddResponse:
        """类型化入口：入参指向 ``StoryMemoryAddRequest``，返回
        ``StoryMemoryAddResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展了 ``id``，均与基类不一致，故必须类型化覆盖 execute 签名。
        实际流程通过 ``super().execute`` 转发，响应类型转换由重写的
        ``_parse_response`` 完成。

        Args:
            use_ai_space_log: ``True``（默认）且 ``__init__`` 传入了
                ``ai_space_log_path`` 时，成功响应会追加一行日志。传 ``False``
                跳过日志写入。
        """
        response = super().execute(request, *args, info_dict=info_dict, **kwargs)
        if (
            use_ai_space_log
            and self._ai_space_log_path
            and response.success
            and response.id
        ):
            append_ai_space_log(
                self._ai_space_log_path,
                is_story=self.is_story,
                album_id=response.id,
                name=request.name,
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
    ) -> StoryMemoryAddResponse:
        """重写基类钩子：用 ``StoryMemoryAddResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``id``）。本方法改用子类的
        ``from_response``，其内部默认展平 ``data`` 嵌套层后，子类字段按
        alias 自动填充。
        """
        return StoryMemoryAddResponse.from_response(raw, trace_id)
