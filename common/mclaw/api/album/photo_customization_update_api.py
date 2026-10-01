#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修改自定义相册（同步接口）。

修改指定自定义相册的名称或封面。**本接口为同步接口**——请求即返回
最终结果，不需要轮询。

接口文档：dev/docs/api/cm-cloud-album.md §22

前置约束：
  - 用户必须已开启智能相册功能
  - ``albumId`` 为已存在的自定义相册 ID
  - 至少指定 ``name`` 或 ``fileId`` 之一（接口语义要求，服务端校验）

响应说明：
  本接口响应为标准信封（``code`` / ``success`` / ``message``），无扩展
  业务字段，``data`` 内无业务字段需展平。基类 ``SyncResponse.from_response``
  默认展平 ``data`` 嵌套层的行为对本接口无副作用（``data`` 为空或不存在），
  无需重写 ``from_response``。但为保持与同子包其他叶子一致的类型化风格，
  仍重写 ``_parse_response`` 指向本接口的 ``PhotoCustomizationUpdateResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header


__all__ = [
    'PhotoCustomizationUpdateRequest',
    'PhotoCustomizationUpdateResponse',
    'PhotoCustomizationUpdateApi',
]


class PhotoCustomizationUpdateRequest(BaseModel):
    """修改自定义相册接口入参。

    本接口属于 album 体系（参数为 ``albumId`` + 可选 ``name`` / ``fileId``），
    与媒体发送型同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/
    sourceTaskId）字段不重合，故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        album_id: 自定义相册 ID（必填）。
        name: 新相册名称（可选；至少与 ``file_id`` 之一非空）。
        file_id: 新封面图片 fileId（可选；至少与 ``name`` 之一非空）。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    album_id: str = Field(..., alias='albumId')
    name: Optional[str] = Field(None, alias='name')
    file_id: Optional[str] = Field(None, alias='fileId')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        ``albumId`` 必填始终携带；``name`` / ``fileId`` 仅在非 None 时输出，
        避免把 ``null`` 透传给服务端覆盖已有值（接口语义为部分更新）。
        """
        payload: Dict[str, Any] = {'albumId': self.album_id}
        if self.name is not None:
            payload['name'] = self.name
        if self.file_id is not None:
            payload['fileId'] = self.file_id
        return payload


class PhotoCustomizationUpdateResponse(SyncResponse):
    """修改自定义相册接口出参（同步返回）。

    无扩展字段——继承基类的 ``success`` / ``code`` / ``message`` / ``trace_id``
    / ``raw``。基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，
    本接口 ``data`` 无业务字段，展平无副作用，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')


@album_api_registry.register('photo_customization_update')
class PhotoCustomizationUpdateApi(BaseSyncApi):
    """修改自定义相册的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/photo/customization/update``，
    请求即返回最终结果（``code`` / ``success`` / ``message``），无 ``taskId``
    轮询。

    Response 无扩展字段，与基类 ``SyncResponse`` 字段集一致；但为保持与同
    子包其他叶子一致的类型化风格，仍重写 ``execute`` 签名 +
    ``_parse_response`` 指向 ``PhotoCustomizationUpdateResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/photo/customization/update'

    api_category = 'album'
    api_label = '修改自定义相册'

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
        request: PhotoCustomizationUpdateRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PhotoCustomizationUpdateResponse:
        """类型化入口：入参指向 ``PhotoCustomizationUpdateRequest``，返回
        ``PhotoCustomizationUpdateResponse``。

        本接口 Request 为 album 体系（非 ``SyncRequest`` 子类），故必须类型化
        覆盖 execute 签名。实际流程通过 ``super().execute`` 转发，响应类型
        转换由重写的 ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> PhotoCustomizationUpdateResponse:
        """重写基类钩子：用 ``PhotoCustomizationUpdateResponse.from_response``
        构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例；本方法改用子类的 ``from_response``，保持与同子包其他叶子
        一致的类型化风格。子类 ``from_response`` 继承基类，默认展平 ``data``
        嵌套层后 ``model_validate``。
        """
        return PhotoCustomizationUpdateResponse.from_response(raw, trace_id)
