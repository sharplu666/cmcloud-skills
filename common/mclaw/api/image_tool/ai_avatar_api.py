#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 头像生成（异步接口）。

将人物照片转换为多种风格的 AI 头像，支持 7 种风格模板
（001/106/107/201/202/203/116）。提交后返回 taskId + queueOffset，
需轮询 ``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/ai_avatar.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse
from mclaw.api.image_tool import image_tool_api_registry
from mclaw.api.image_tool._model import ImageToolAsyncApi, StyledImageToolRequest


__all__ = [
    'AiAvatarRequest',
    'AiAvatarApi',
]


class AiAvatarRequest(StyledImageToolRequest):
    """AI 头像生成接口入参。

    继承 ``StyledImageToolRequest``（统一 ``to_payload`` + style/supplierType
    字段），仅覆盖两个业务默认值：
      - ``style``：头像风格编码，默认 ``'116'``（3D 风格）
      - ``supplier_type``：厂商类型，默认 ``4``（腾讯）
    """

    style: Optional[str] = Field('116', alias='style')
    supplier_type: Optional[int] = Field(4, alias='supplierType')


@image_tool_api_registry.register('ai_avatar')
class AiAvatarApi(ImageToolAsyncApi):
    """AI 头像生成的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/avatar/cartoon``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。

    终态日志脱敏由 ``ImageToolAsyncApi._build_result_dict`` 统一处理，遮蔽
    ``fileInfoList`` 内的长串/哈希字段。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/avatar/cartoon'

    api_category = 'avatar'
    api_label = 'AI头像生成'

    def execute(
        self,
        request: AiAvatarRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``AiAvatarRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
