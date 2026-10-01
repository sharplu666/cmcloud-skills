#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 扩图（异步接口）。

将图片向四个方向（上下左右）扩展，AI 自动生成延伸的背景内容，支持自由比例和
预设比例（1:1 / 9:16 / 16:9 / 3:4 / 4:3 / 3:2 / 2:3）扩图。提交后返回
taskId + queueOffset，需轮询 ``/richlifeApp/aiService/api/async/task/result``
获取结果。

接口文档：dev/docs/api/ai_expand_image.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'ExpandRatio',
    'AiExpandImageRequest',
    'AiExpandImageApi',
]


class ExpandRatio(BaseModel):
    """扩图参数对象（嵌套在请求的 expandRatio 字段下）。

    Attributes:
        top: 向上扩展像素，精度保留到小数点后 3 位。
        bottom: 向下扩展像素。
        left: 向左扩展像素。
        right: 向右扩展像素。
        ratio: 比例：``自由`` / ``1:1`` / ``9:16`` / ``16:9`` /
            ``3:4`` / ``4:3`` / ``3:2`` / ``2:3``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    top: Optional[float] = None
    bottom: Optional[float] = None
    left: Optional[float] = None
    right: Optional[float] = None
    ratio: str


class AiExpandImageRequest(AsyncSubmitRequest):
    """AI 扩图接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展本接口的两个业务字段：
      - ``expand_ratio``：扩图参数对象（嵌套 ``ExpandRatio``）
      - ``supplier_type``：厂商类型，默认 ``8``（美图）

    重写 ``to_payload`` 以确保 ``expandRatio`` 嵌套对象按 camelCase 序列化为
    接口文档要求的结构，避免基类默认 ``model_dump`` 把嵌套 BaseModel 展开为
    snake_case 字段。
    """

    expand_ratio: ExpandRatio = Field(..., alias='expandRatio')
    supplier_type: Optional[int] = Field(8, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名 + 嵌套对象）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``，
        对 ``expand_ratio`` 嵌套 BaseModel 的内部字段无法保证 camelCase 输出
        （Pydantic v2 默认按内层 model 自身字段名序列化）。这里显式调用嵌套
        对象的 ``model_dump(by_alias=True, exclude_none=True)`` 保证与接口文档
        对齐；其余顶层字段手工拼装，避免带入 exclude=True 的轮询占位字段。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext.lower().lstrip("."),
            'expandRatio': self.expand_ratio.model_dump(
                by_alias=True, exclude_none=True
            ),
            'supplierType': self.supplier_type,
        }
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('ai_expand_image')
class AiExpandImageApi(BaseAsyncApi):
    """AI 扩图的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/expand``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/expand'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'expand'
    api_label = 'AI扩图'

    def execute(
        self,
        request: AiExpandImageRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``AiExpandImageRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
