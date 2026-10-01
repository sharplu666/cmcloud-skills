#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片去重（同步接口）。

对一组个人云图片执行去重：每个重复分组只保留图片质量评分最高的一张，
最终返回去重后的文件 ID 列表。**本接口为同步接口**——请求即返回最终结果，
不需要轮询。

接口文档：dev/docs/api/album/image_deduplicate.md

前置约束：
  - 图片必须为个人云图片
  - 用户必须已开启智能相册功能
  - ``fileIdList`` 数量不超过 1000

响应说明：
  本接口响应 ``data`` 含 ``nonsimilarFileIdList`` 业务字段。基类
  ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，子类业务字段
  （带 alias）会被自动填充；但 ``BaseSyncApi._parse_response`` 硬编码用
  基类 ``SyncResponse.from_response`` 解析，识别不了子类，故需重写
  ``_parse_response`` 指向本接口的 ``ImageDeduplicateResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry


__all__ = [
    'ImageDeduplicateRequest',
    'ImageDeduplicateResponse',
    'ImageDeduplicateApi',
    'MAX_FILE_ID_LIST_SIZE',
]


#: ``fileIdList`` 单次请求上限（接口约束）。同时作为对外契约供编排层
#: （如 ``cm_cloud_organize/scripts/image_deduplicator.py`` 的分批逻辑）引用，
#: 对齐 ``cm_cloud_http.py`` 的 ``IMAGE_DEDUPLICATE_MAX_BATCH`` 暴露模式。
MAX_FILE_ID_LIST_SIZE: int = 1000


class ImageDeduplicateRequest(BaseModel):
    """图片去重接口入参。

    本接口属于 cloudId 体系（参数为 ``fileIdList``），与媒体发送型同步基类
    ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）字段不重合，
    故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        file_id_list: 图片 ID 列表（个人云图片 fileId），数量不超过
            ``MAX_FILE_ID_LIST_SIZE``（1000）；超限在构造阶段抛
            ``ValidationError``，阻止无效请求触达服务端。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    file_id_list: List[str] = Field(..., alias='fileIdList')

    @field_validator('file_id_list')
    @classmethod
    def _check_max_size(cls, value: List[str]) -> List[str]:
        """接口约束：fileIdList 单次不超过 ``MAX_FILE_ID_LIST_SIZE``。"""
        if len(value) > MAX_FILE_ID_LIST_SIZE:
            raise ValueError(
                f'fileIdList 单次不超过 {MAX_FILE_ID_LIST_SIZE}，收到 {len(value)}'
            )
        return value

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。"""
        return {'fileIdList': list(self.file_id_list)}


class ImageDeduplicateResponse(SyncResponse):
    """图片去重接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``nonsimilar_file_id_list``：去重后的文件 ID 列表（每个重复分组仅
        保留质量评分最高的一张）。接口文档标注为可选（O），实际成功响应
        中总会返回；为防御性处理，默认值为 ``None``。

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故该字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    nonsimilar_file_id_list: Optional[List[str]] = Field(
        default=None, alias='nonsimilarFileIdList'
    )


@album_api_registry.register('image_deduplicate')
class ImageDeduplicateApi(BaseSyncApi):
    """图片去重的同步 API。

    路径 ``POST /richlifeApp/aiService/api/image/deduplicate``，请求即返回
    最终结果（``nonsimilarFileIdList``），无 ``taskId`` 轮询。

    Response 字段扩展了 ``nonsimilar_file_id_list``，与基类 ``SyncResponse``
    不一致，故必须类型化 ``execute`` 签名 + 重写 ``_parse_response`` 指向
    ``ImageDeduplicateResponse``。
    """

    PATH = '/richlifeApp/aiService/api/image/deduplicate'

    #: ``fileIdList`` 单次上限（re-export 模块常量，供编排层引用）。
    MAX_FILE_ID_LIST_SIZE = MAX_FILE_ID_LIST_SIZE

    api_category = 'album'
    api_label = '图片去重'

    def execute(
        self,
        request: ImageDeduplicateRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ImageDeduplicateResponse:
        """类型化入口：入参指向 ``ImageDeduplicateRequest``，返回
        ``ImageDeduplicateResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展了 ``nonsimilar_file_id_list``，均与基类不一致，故必须类型化
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
    ) -> ImageDeduplicateResponse:
        """重写基类钩子：用 ``ImageDeduplicateResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``nonsimilar_file_id_list``）。
        本方法改用子类的 ``from_response``，其内部默认展平 ``data`` 嵌套层后，
        子类字段按 alias 自动填充。
        """
        return ImageDeduplicateResponse.from_response(raw, trace_id)
