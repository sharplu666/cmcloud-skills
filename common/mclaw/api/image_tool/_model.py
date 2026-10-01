#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_tool 异步接口的共享模型基类。

``style + supplierType`` 型异步接口（ai_avatar / ai_retouch 等）的请求体结构
高度一致：``sendType`` / ``imageExt`` / ``style`` / ``supplierType`` +
``fileUrl|fileId`` + ``sourceTaskId``，且响应都走 ``resultList/fileInfoList``
结构（需终态日志脱敏）。本模块抽出：

  - ``StyledImageToolRequest``：统一 ``to_payload`` 与 style/supplierType 字段声明
  - ``ImageToolAsyncApi``：统一终态日志脱敏（委托 ``_redact``）

子类只需声明字段默认值与 ``SUBMIT_PATH``，无需复制 ``to_payload`` /
``_build_result_dict``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncSubmitRequest, BaseAsyncApi


__all__ = ['StyledImageToolRequest', 'ImageToolAsyncApi']


class StyledImageToolRequest(AsyncSubmitRequest):
    """带 ``style`` / ``supplierType`` 的 image_tool 异步请求基类。

    统一 ``to_payload``：``sendType`` / ``imageExt`` / ``style`` / ``supplierType``
    + ``fileUrl|fileId`` + ``sourceTaskId``。子类按需覆盖 ``style`` /
    ``supplier_type`` 默认值（如 AiAvatar 默认 116/4，AiRetouch 默认 1/8）。
    """

    style: Optional[str] = Field(None, alias='style')
    supplier_type: Optional[int] = Field(None, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``AsyncSubmitRequest.to_payload`` 做
        ``model_dump(by_alias=True, exclude_none=True)``，但同时会带上
        ``exclude=True`` 的轮询字段占位。为确保只输出接口文档字段，重新构造
        payload：sendType/imageExt/style/supplierType + fileUrl|fileId +
        sourceTaskId。
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


class ImageToolAsyncApi(BaseAsyncApi):
    """image_tool 异步 API 共享基类：内置终态日志脱敏。

    子类设置 ``SUBMIT_PATH`` / ``api_category`` / ``api_label``，并按需类型化
    ``execute``。``_build_result_dict`` 统一委托
    ``_redact.redact_image_tool_result``，遮蔽 ``resultList/fileInfoList`` 内的
    长串 URL 与哈希，精简日志。
    """

    # SUBMIT_PATH 由子类声明；POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    def _build_result_dict(
        self,
        response: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """终态日志结果脱敏：遮蔽 resultList 内的长串/哈希字段，精简日志。"""
        from mclaw.api.image_tool._redact import redact_image_tool_result
        return redact_image_tool_result(response.raw)
