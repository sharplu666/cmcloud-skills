#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能抠图（异步接口）。

对含人物的图片进行智能抠图，自动识别人物轮廓并生成透明背景的抠图结果。
提交后返回 taskId + queueOffset，需轮询
``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/human_matting.md

本接口的请求字段在 ``AsyncSubmitRequest`` 基类基础上扩展 ``supplierType``
（厂商类型，默认 ``8`` 美图，与老版本 retouch_api.py 硬编码值一致），
响应字段与 ``AsyncPollResponse`` 基类完全一致，因此：
  - 仅定义 ``HumanMattingRequest`` 子类扩展 supplier_type 字段
  - 响应沿用 ``AsyncPollResponse``，不定义 Response 子类
  - 重写 ``execute`` 签名指向 ``HumanMattingRequest``
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'HumanMattingRequest',
    'HumanMattingApi',
]


class HumanMattingRequest(AsyncSubmitRequest):
    """智能抠图接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展 ``supplier_type``：厂商类型，默认 ``8``
    （美图），与老版本 retouch_api.py 硬编码值一致。

    重写 ``to_payload`` 以确保 supplierType 按 camelCase 进入 payload，
    并按 ``sendType`` 选择 ``fileUrl`` 或 ``fileId``。
    """

    supplier_type: Optional[int] = Field(8, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``，
        会带上 exclude=True 的轮询字段占位。为确保只输出接口文档字段，
        重新构造 payload。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext.lower().lstrip("."),
            'supplierType': self.supplier_type,
        }
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('human_matting')
class HumanMattingApi(BaseAsyncApi):
    """智能抠图的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/edit/imageCutout``，
    轮询路径沿用基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    请求扩展 ``supplierType``（默认 8），响应字段与基类 ``AsyncPollResponse``
    完全一致，无需扩展 Response 子类。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/edit/imageCutout'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'edit'
    api_label = '智能抠图'

    def execute(
        self,
        request: HumanMattingRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``HumanMattingRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
