#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人脸美颜（异步接口）。

对人像照片进行智能美颜处理，提供 5 种美颜风格（1 原生 / 2 自然 / 3 轻妆 /
4 精修 / 5 焕颜）。提交后返回 taskId + queueOffset，需轮询
``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/ai_retouch.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse
from mclaw.api.image_tool import image_tool_api_registry
from mclaw.api.image_tool._model import ImageToolAsyncApi, StyledImageToolRequest


__all__ = [
    'AiRetouchRequest',
    'AiRetouchApi',
]


class AiRetouchRequest(StyledImageToolRequest):
    """人脸美颜接口入参。

    继承 ``StyledImageToolRequest``（统一 ``to_payload`` + style/supplierType
    字段），仅覆盖两个业务默认值：
      - ``style``：美颜风格，默认 ``'1'``（原生）。可选 1/2/3/4/5
      - ``supplier_type``：厂商类型，默认 ``8``（美图）

    与 ``AiAvatarRequest`` 一致，本接口 ``style`` 为 ``str`` 类型
    （对齐老版本 build_payload 中的字符串处理）。
    """

    style: Optional[str] = Field('1', alias='style')
    supplier_type: Optional[int] = Field(8, alias='supplierType')


@image_tool_api_registry.register('ai_retouch')
class AiRetouchApi(ImageToolAsyncApi):
    """人脸美颜的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/beautify/face``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。

    终态日志脱敏由 ``ImageToolAsyncApi._build_result_dict`` 统一处理，遮蔽
    ``fileInfoList`` 内的长串/哈希字段。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/beautify/face'

    api_category = 'beautify'
    api_label = '智能美颜'

    def execute(
        self,
        request: AiRetouchRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``AiRetouchRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
