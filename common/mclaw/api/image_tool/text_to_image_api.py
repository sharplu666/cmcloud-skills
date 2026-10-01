#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文生图（异步接口）。

根据用户输入的文本描述（prompt），使用 AI 生成全新的图片。支持 4 种风格
（1/2/3/4）和 3 种分辨率（512x512 / 512x683 / 683x512）。提交后返回
taskId + queueOffset，需轮询 ``/richlifeApp/aiService/api/async/task/result``
获取结果。

接口文档：dev/docs/api/text_to_image.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import AsyncPollResponse, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'TextToImageRequest',
    'TextToImageApi',
]


class TextToImageRequest(BaseModel):
    """文生图接口入参。

    本接口入参为 ``prompt`` / ``style`` / ``width`` / ``height``，与媒体发送型
    异步基类 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/...）字段不重合，
    故直接继承 ``pydantic.BaseModel``，并自带轮询控制字段
    （``poll_interval`` / ``poll_max_attempts``，``exclude=True``）供
    ``BaseAsyncApi._poll`` 使用。

    Attributes:
        prompt: 生成提示词。
        style: 风格编码（字符串）—— ``'1'`` 时尚俊男靓女 / ``'2'`` 提升角色面部
            精细度 / ``'3'`` 清新经典动画风格 / ``'4'`` 中国风水墨水彩。
        width: 分辨率宽度，需和 ``height`` 成对传入。
        height: 分辨率高度，需和 ``width`` 成对传入。
        supplier_type: 厂商类型，默认 ``8``（美图）。
        source_task_id: 任务幂等 ID。
        poll_interval: 轮询间隔（秒），不进 payload。
        poll_max_attempts: 最大轮询次数，不进 payload。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    prompt: str = Field(..., alias='prompt')
    style: str = Field(..., alias='style')
    width: Optional[int] = Field(None, alias='width')
    height: Optional[int] = Field(None, alias='height')
    supplier_type: Optional[int] = Field(8, alias='supplierType')
    source_task_id: Optional[int] = Field(None, alias='sourceTaskId')

    # 轮询控制（由 BaseAsyncApi._poll 读取，不进 payload）
    poll_interval: float = Field(2.0, exclude=True)
    poll_max_attempts: int = Field(60, exclude=True)

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        只输出接口文档字段，不携带轮询控制参数。``width``/``height`` 为 None 时
        省略（文档要求成对传入，不传表示服务端默认分辨率）。
        """
        payload: Dict[str, Any] = {
            'prompt': self.prompt,
            'style': self.style,
            'supplierType': self.supplier_type,
        }
        if self.width is not None:
            payload['width'] = self.width
        if self.height is not None:
            payload['height'] = self.height
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('text_to_image')
class TextToImageApi(BaseAsyncApi):
    """文生图的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/textToImage``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/textToImage'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'generate'
    api_label = '文生图'

    def execute(
        self,
        request: TextToImageRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``TextToImageRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
