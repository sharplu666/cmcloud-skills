#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 漫画风（异步接口）。

将人物照片转换为动漫/漫画风格图片，支持多种风格
（``0``/``1``/``2``/``106``/``107``/``116``/``201``/``jpcartoon_head``/
``jpcartoon``/``hkcartoon``/``classic_cartoon``/``tccartoon``）。
默认 ``supplier_type=0``（自研）覆盖 ``0``/``1``/``2`` 三个核心枚举；其余 style
需调用方显式传入对应的 ``supplier_type``（腾讯 4 / 火山 7）。
提交后返回 taskId + queueOffset，需轮询
``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/image_comic_style.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'ImageComicStyleRequest',
    'ImageComicStyleApi',
]


class ImageComicStyleRequest(AsyncSubmitRequest):
    """AI 漫画风接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展本接口的两个业务字段：
      - ``style``：漫画风格编码（字符串），可选。``None`` 时不发 style 字段，
        交由接口默认处理。默认 ``None``。
      - ``supplier_type``：厂商类型，默认 ``0``（自研）

    supplierType 与 style 的对应关系（同 legacy ``retouch_api.py`` 的
    ``STYLE_TO_SUPPLIER_TYPE``）：自研（0）仅支持 ``0``/``1``/``2`` 三个核心枚举；
    腾讯（4）支持 ``106``/``107``/``116``/``201``；火山（7）支持 ``jpcartoon``
    系列等扩展串。默认取自研（0）与本项目内 AI 能力的常规兜底厂商一致；
    调用方使用非自研支持的 style 时需显式传入对应的 ``supplier_type``。

    重写 ``to_payload`` 以确保 style/supplierType 按 camelCase 进入 payload。
    """

    style: Optional[str] = Field(None, alias='style')
    supplier_type: Optional[int] = Field(0, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``，
        已涵盖 sendType/fileUrl/fileId/imageExt/sourceTaskId/style/supplierType，
        但同时会带上 exclude=True 的轮询字段占位。为确保只输出接口文档字段，
        重新构造 payload。``style=None`` 时不发 style 字段，对齐老版本行为。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext.lower().lstrip("."),
            'supplierType': self.supplier_type,
        }
        if self.style is not None:
            payload['style'] = self.style
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('image_comic_style')
class ImageComicStyleApi(BaseAsyncApi):
    """AI 漫画风的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/edit/faceAnime``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。

    终态日志对 ``fileInfoList`` 内的长串/哈希字段脱敏（见
    ``image_tool._redact``），精简日志输出。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/edit/faceAnime'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'comic'
    api_label = 'AI漫画风'

    def execute(
        self,
        request: ImageComicStyleRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``ImageComicStyleRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _build_result_dict(
        self,
        response: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """终态日志结果脱敏：遮蔽 ``resultList`` 内的长串/哈希字段，精简日志。"""
        from mclaw.api.image_tool._redact import redact_image_tool_result
        return redact_image_tool_result(response.raw)
