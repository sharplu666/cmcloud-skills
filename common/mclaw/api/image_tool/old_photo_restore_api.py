#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""老照片修复（异步接口）。

对模糊、破损、低质量的老旧照片进行智能修复，提升清晰度和画面质量。提供两种
修复模式：``0`` 人像修复 / ``1`` 通用修复。提交后返回 taskId + queueOffset，
需轮询 ``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/old_photo_restore.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'OldPhotoRestoreRequest',
    'OldPhotoRestoreApi',
]


class OldPhotoRestoreRequest(AsyncSubmitRequest):
    """老照片修复接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展本接口的两个业务字段：
      - ``style``：修复模式（字符串），``'0'`` 人像修复 / ``'1'`` 通用修复。
        对齐老版本 str 类型。
      - ``supplier_type``：厂商类型，默认 ``8``（美图）；文档标注另支持火山（``7``）

    重写 ``to_payload`` 以确保 style/supplierType 按 camelCase 进入 payload。
    本接口 ``style`` 为 ``str`` 类型（对齐老版本 build_payload 中的字符串处理）。
    """

    style: Optional[str] = Field(None, alias='style')
    supplier_type: Optional[int] = Field(8, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``，
        已涵盖 sendType/fileUrl/fileId/imageExt/sourceTaskId/style/supplierType，
        但同时会带上 exclude=True 的轮询字段占位。为确保只输出接口文档字段，
        重新构造 payload。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext.lower().lstrip("."),
            'style': self.style,
            'supplierType': self.supplier_type,
        }
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('old_photo_restore')
class OldPhotoRestoreApi(BaseAsyncApi):
    """老照片修复的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/restore/oldPhoto``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/restore/oldPhoto'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'restore'
    api_label = '老照片修复'

    def execute(
        self,
        request: OldPhotoRestoreRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``OldPhotoRestoreRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
