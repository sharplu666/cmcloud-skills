#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画质修复（异步接口）。

提升图片清晰度和分辨率，支持 2/4/8 倍超分辨率放大。提交后返回 taskId +
queueOffset，需轮询 ``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/image_enhance.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'ImageEnhanceRequest',
    'ImageEnhanceApi',
]


class ImageEnhanceRequest(AsyncSubmitRequest):
    """画质修复接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展本接口的两个业务字段：
      - ``multiple``：放大倍数（2/4/8），为 ``None`` 时不传，由服务端应用默认值
      - ``supplier_type``：厂商类型，默认 ``8``（美图）

    重写 ``to_payload`` 以确保 ``multiple=None`` 时字段被省略（不发送 ``null``）。
    """

    multiple: Optional[int] = Field(None, alias='multiple')
    supplier_type: Optional[int] = Field(8, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``，
        但 ``supplier_type`` 默认值 ``8`` 会随 exclude_none 一并带上，而 ``multiple``
        为 ``None`` 时会被排除。为确保字段集合与文档一致并显式控制 multiple 的
        省略行为，这里重新构造 payload：先填必填字段，再条件性追加 multiple。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext,
            'supplierType': self.supplier_type,
        }
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        # multiple=None 时省略字段，让服务端应用默认值（不发送 null）
        if self.multiple is not None:
            payload['multiple'] = self.multiple
        return payload


@image_tool_api_registry.register('image_enhance')
class ImageEnhanceApi(BaseAsyncApi):
    """画质修复的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/quality/repair``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/quality/repair'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'quality'
    api_label = '画质修复'

    def execute(
        self,
        request: ImageEnhanceRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``ImageEnhanceRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
