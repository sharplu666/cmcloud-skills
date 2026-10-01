#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义相册加图（同步接口）。

向指定自定义相册中添加图片文件。**本接口为同步接口**——请求即返回
最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §21（自定义相册加图）

前置约束：
  - 用户必须已开启智能相册功能
  - ``albumId`` 为已存在的自定义相册 ID
  - ``fileIds`` 为个人云图片 fileId 列表

响应说明：
  本接口响应为标准信封（``code`` / ``success`` / ``message``），无扩展业务
  字段，``data`` 内无业务字段需展平。基类 ``SyncResponse.from_response``
  默认展平 ``data`` 嵌套层的行为对本接口无副作用（``data`` 为空或不存在），
  无需重写 ``from_response``。但为保持与同子包其他叶子一致的类型化风格，
  仍重写 ``_parse_response`` 指向本接口的 ``PhotoCustomizationFileAddResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.base._ai_space_log import append_ai_space_log


__all__ = [
    'PhotoCustomizationFileAddRequest',
    'PhotoCustomizationFileAddResponse',
    'PhotoCustomizationFileAddApi',
]


class PhotoCustomizationFileAddRequest(BaseModel):
    """自定义相册加图接口入参。

    本接口属于 album 体系（参数为 ``albumId`` + ``fileIds``），与媒体发送型
    同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）
    字段不重合，故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        album_id: 自定义相册 ID
        file_ids: 图片 fileId 列表（个人云图片 fileId）
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    album_id: str = Field(..., alias='albumId')
    file_ids: List[str] = Field(..., alias='fileIds')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。"""
        return {'albumId': self.album_id, 'fileIds': list(self.file_ids)}


class PhotoCustomizationFileAddResponse(SyncResponse):
    """自定义相册加图接口出参（同步返回）。

    无扩展字段——继承基类的 ``success`` / ``code`` / ``message`` / ``trace_id``
    / ``raw``。基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，
    本接口 ``data`` 无业务字段，展平无副作用，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')


@album_api_registry.register('photo_customization_file_add')
class PhotoCustomizationFileAddApi(BaseSyncApi):
    """自定义相册加图的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/photo/customization/file/add``，
    请求即返回最终结果（``code`` / ``success`` / ``message``），无 ``taskId``
    轮询。

    Response 无扩展字段，与基类 ``SyncResponse`` 字段集一致；但为保持与同子包
    其他叶子一致的类型化风格，仍重写 ``execute`` 签名 + ``_parse_response``
    指向 ``PhotoCustomizationFileAddResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/photo/customization/file/add'

    api_category = 'album'
    api_label = '自定义相册加图'

    is_story: bool = False

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
                会向该文件追加一行 ``{"albumId": "<id>", "type": "album"}``，
                用于追踪归档链路。
                默认 ``None``，向后兼容不写日志。
        """
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_album_header
        self._ai_space_log_path = ai_space_log_path or ''

    def execute(
        self,
        request: PhotoCustomizationFileAddRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        use_ai_space_log: bool = True,
        **kwargs: Any,
    ) -> PhotoCustomizationFileAddResponse:
        """类型化入口：入参指向 ``PhotoCustomizationFileAddRequest``，返回
        ``PhotoCustomizationFileAddResponse``。

        本接口 Request 为 album 体系（非 ``SyncRequest`` 子类），故必须类型化
        覆盖 execute 签名。实际流程通过 ``super().execute`` 转发，响应类型
        转换由重写的 ``_parse_response`` 完成。

        Args:
            use_ai_space_log: ``True``（默认）且 ``__init__`` 传入了
                ``ai_space_log_path`` 时，成功响应会追加一行日志。传 ``False``
                跳过日志写入。日志记录的 ``albumId`` 取自 ``request.album_id``。
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
                record_type='album',
                logger=self.logger,
            )
        return response

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> PhotoCustomizationFileAddResponse:
        """重写基类钩子：用 ``PhotoCustomizationFileAddResponse.from_response``
        构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例；本方法改用子类的 ``from_response``，保持与同子包其他叶子
        一致的类型化风格。子类 ``from_response`` 继承基类，默认展平 ``data``
        嵌套层后 ``model_validate``。
        """
        return PhotoCustomizationFileAddResponse.from_response(raw, trace_id)
