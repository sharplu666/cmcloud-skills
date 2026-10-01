#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""活照片（异步接口）。

将静态人物照片生成动态视频效果，让照片中的人物做出眨眼、微笑等动作。
支持两种风格：``0`` 头像版（默认） / ``1`` 全身版。提交后返回 taskId +
queueOffset，需轮询 ``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/live_photo.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse
from mclaw.api.image_tool import image_tool_api_registry
from mclaw.api.image_tool._model import ImageToolAsyncApi, StyledImageToolRequest


__all__ = [
    'LivePhotoRequest',
    'LivePhotoApi',
]


class LivePhotoRequest(StyledImageToolRequest):
    """活照片接口入参。

    继承 ``StyledImageToolRequest``（统一 ``to_payload`` + style/supplierType
    字段），仅覆盖两个业务默认值：
      - ``style``：动画类型，默认 ``'1'``（对齐老版本 str 类型）
      - ``supplier_type``：厂商类型，默认 ``7``（火山）
    """

    style: Optional[str] = Field('1', alias='style')
    supplier_type: Optional[int] = Field(7, alias='supplierType')


@image_tool_api_registry.register('live_photo')
class LivePhotoApi(ImageToolAsyncApi):
    """活照片的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/alivePhoto``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。

    终态日志脱敏由 ``ImageToolAsyncApi._build_result_dict`` 统一处理，遮蔽
    ``fileInfoList`` 内的长串/哈希字段（活照片结果为 .mp4 视频 URL，同样冗长）。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/alivePhoto'

    api_category = 'animate'
    api_label = '活照片'

    def execute(
        self,
        request: LivePhotoRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``LivePhotoRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
