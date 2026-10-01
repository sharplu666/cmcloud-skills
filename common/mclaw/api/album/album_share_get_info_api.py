#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""相册分享信息查询（同步接口）。

对一组云盘图片创建相册分享链接，返回分享 URL 与分享侧相册元信息。**本接口
为同步接口**——请求即返回最终结果，不需要轮询。

鉴权说明：
  本接口使用 ``mclaw.api.album._get_auth.get_album_share_header`` 作为鉴权头，
  在标准云盘鉴权头基础上追加 ``Content-Type`` / ``x-yun-client-info`` /
  ``x-DeviceInfo`` 三个字段（对齐 legacy ``cm_cloud_http.py`` 的
  ``_send_request(header_type='share')`` 链路）。覆盖在子类 ``__init__`` 中
  完成，调用方通过 ``ApiDispatcher`` 注入的 ``auth_fn`` 不再被本接口使用
  （但 ``host`` / ``logger`` 等仍由基类统一管理）。

接口文档：dev/docs/api/cm-cloud-album.md §23

响应说明：
  本接口响应为**特殊信封** ``{code:0/'0', msg, ret:{...}}``，**不是** 标准
  ``{code:'0000', success, data:{...}}``。``code`` 为整数 ``0`` 或字符串
  ``'0'`` 均视为成功，``ret`` 承载数据（替代 ``data``）。故必须重写
  ``from_response`` 从 ``ret`` 提取业务字段；同时重写 ``_parse_response``
  指向本接口的 ``AlbumShareGetInfoResponse``。

请求预处理：
  ``content_ids: List[str]`` 在 ``to_payload`` 中映射为
  ``photos[{sort:i+1, contentID:cid}]``（``sort`` 从 1 开始）。内置
  ``needWatermark=0``、``visitUnlimited=1``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_share_header
from mclaw.api.album._models import PhotoItem


__all__ = [
    'AlbumShareGetInfoRequest',
    'AlbumShareGetInfoResponse',
    'AlbumShareGetInfoApi',
]


class AlbumShareGetInfoRequest(BaseModel):
    """相册分享信息查询接口入参。

    本接口属于 cloudId 体系（参数为 ``contentIds``），与媒体发送型同步基类
    ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）字段不重合，
    故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        album_name: 分享页展示的相册名称。
        album_showtime: 分享页展示的时间文案。
        album_type: 相册类型：``1``=回忆/故事相册，``2``=普通相册。
        story_id: 相册或故事 ID。
        content_ids: 待分享图片的云盘 fileId 列表，``to_payload`` 中按顺序
            映射为 ``photos[{sort:i+1, contentID:cid}]``。
        share_time_type: 有效期：``1``=一天，``2``=七天，``3``=永久。可选，
            不传则由服务端默认。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    album_name: str = Field(..., alias='albumName')
    album_showtime: str = Field(..., alias='albumShowtime')
    album_type: int = Field(..., alias='albumType')
    story_id: str = Field(..., alias='storyId')
    content_ids: List[str] = Field(..., alias='contentIds')
    share_time_type: Optional[int] = Field(None, alias='shareTimeType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        - ``content_ids`` 映射为 ``photos[{sort:i+1, contentID:cid}]``
          （``sort`` 从 1 开始递增）。
        - 内置 ``needWatermark=0``（不需要水印）、``visitUnlimited=1``
          （无限次访问）。
        - ``shareTimeType`` 仅在非 None 时包含。
        """
        photos = [
            PhotoItem(sort=i + 1, content_id=cid).model_dump(by_alias=True)
            for i, cid in enumerate(self.content_ids)
        ]
        payload: Dict[str, Any] = {
            'albumName': self.album_name,
            'albumShowtime': self.album_showtime,
            'albumType': self.album_type,
            'storyId': self.story_id,
            'photos': photos,
            'needWatermark': 0,
            'visitUnlimited': 1,
        }
        if self.share_time_type is not None:
            payload['shareTimeType'] = self.share_time_type
        return payload


class AlbumShareGetInfoResponse(SyncResponse):
    """相册分享信息查询接口出参（同步返回）。

    扩展字段对应响应 ``ret`` 内的业务字段（§23）：
      - ``url``：分享链接。
      - ``album_id``：分享侧相册 ID。
      - ``album_name``：分享侧相册名称。
      - ``mood``：心情标签。

    本接口响应为**特殊信封** ``{code:0(int), msg, ret:{...}}``，``ret`` 替代
    标准 ``data``。基类 ``SyncResponse.from_response`` 默认展平 ``data``，无法
    识别 ``ret``，故**必须重写 ``from_response``**：从 ``ret`` 提取业务字段，
    按 alias 自动映射到子类字段。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    url: Optional[str] = Field(None, alias='url')
    album_id: Optional[str] = Field(None, alias='albumId')
    album_name: Optional[str] = Field(None, alias='albumName')
    mood: Optional[str] = Field(None, alias='mood')

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'AlbumShareGetInfoResponse':
        """从特殊信封 ``{code:int, msg, ret:{...}}`` 构造响应。

        ``code`` 为 ``0`` / ``'0'`` 视为成功，``ret`` 承载数据（替代 ``data``）。
        业务字段从 ``ret`` 提取，按 alias 自动映射到子类字段。
        线上环境 ``code`` 可能是字符串 ``'0'``，且信封自带 ``success: true``；
        不可只用 ``code == 0``（整数），否则会把成功判成失败并出现
        「相册分享失败: success」。
        """
        code = raw.get('code')
        success = str(code).strip() in ('0', '0000') or raw.get('success') is True
        ret = raw.get('ret') or {}
        # 合并：ret 业务字段 + 外层 success/code/message + trace_id
        merged = {
            **ret,
            'success': success,
            'code': str(code) if code is not None else '',
            'message': raw.get('msg', ''),
            'trace_id': trace_id,
        }
        instance = cls.model_validate(merged)
        object.__setattr__(instance, 'raw', raw)
        return instance


@album_api_registry.register('album_share_get_info')
class AlbumShareGetInfoApi(BaseSyncApi):
    """相册分享信息查询的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/share/getAlbumShareInfo``，
    请求即返回最终结果（``url`` / ``albumId`` 等），无 ``taskId`` 轮询。

    鉴权头使用 ``get_album_share_header``（在标准云盘鉴权头基础上追加
    ``Content-Type`` / ``x-yun-client-info`` / ``x-DeviceInfo`` 三个字段，
    对齐 legacy ``cm_cloud_http.py`` 的 ``_send_request(header_type='share')``
    链路）。覆盖在 ``__init__`` 中完成：调用方通过 ``ApiDispatcher`` 注入的
    ``auth_fn`` 不被本接口使用，但 ``host`` / ``logger`` 仍由基类统一管理。

    Response 字段扩展了 ``url`` / ``album_id`` / ``album_name`` / ``mood``，
    且响应信封特殊（``ret`` 替代 ``data``），与基类 ``SyncResponse`` 不一致，
    故必须类型化 ``execute`` 签名 + 重写 ``_parse_response`` 指向
    ``AlbumShareGetInfoResponse``。
    """

    PATH = '/richlifeApp/personalSaas/album/share/getAlbumShareInfo'

    api_category = 'album'
    api_label = '获取相册分享信息'

    def __init__(
        self,
        host: str,
        auth_fn: Any,
        logger: Any = None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        """注入 share 端点专用鉴权头。

        ``auth_fn`` 参数仍按基类签名接收（保持 ``ApiDispatcher`` 统一注入
        契约），但本接口不使用该 ``auth_fn``，而是覆盖为
        ``get_album_share_header``。``host`` / ``logger`` / ``redact_params``
        仍透传给基类。

        ``get_album_share_header`` 内部调 ``get_auth_header`` →
        ``get_skill_auth`` → ``_read_env_values``，每次请求都实时读取 ``.env``，
        token 文件更新后下次请求即生效（动态读取特性）。
        """
        super().__init__(host, auth_fn, logger, redact_params)
        # 覆盖为 share 端点专用鉴权头（加 x-DeviceInfo）
        # get_album_share_header 每次调用都重读 .env，故无需 closure 包装
        self._auth = get_album_share_header

    def execute(
        self,
        request: AlbumShareGetInfoRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AlbumShareGetInfoResponse:
        """类型化入口：入参指向 ``AlbumShareGetInfoRequest``，返回
        ``AlbumShareGetInfoResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展且信封特殊，均与基类不一致，故必须类型化覆盖 execute 签名。
        实际流程通过 ``super().execute`` 转发，响应类型转换由重写的
        ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> AlbumShareGetInfoResponse:
        """重写基类钩子：用 ``AlbumShareGetInfoResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``url`` / ``album_id`` 等）与
        特殊信封（``ret`` 替代 ``data``）。本方法改用子类的 ``from_response``，
        其内部从 ``ret`` 提取业务字段后按 alias 自动填充。
        """
        return AlbumShareGetInfoResponse.from_response(raw, trace_id)
