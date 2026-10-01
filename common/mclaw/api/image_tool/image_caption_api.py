#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片配文（异步接口）。

智能分析图片内容并生成合适的文字配文。提交后返回 taskId + queueOffset，
需轮询 ``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/image_caption.md

响应说明：
  本接口最终结果不在基类默认的 ``data.resultList`` 中，而是落在
  ``data.textList``（每条包含文字内容与匹配度分数）。因此扩展
  ``AsyncPollResponse`` 增加 ``text_list`` 字段，并通过 ``_build_result``
  钩子从 ``raw.data.textList`` 提取。详见 dev/skills/image_tool/image_caption/index.md
  「结果总结」一节。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'ImageCaptionRequest',
    'ImageCaptionPollResponse',
    'ImageCaptionApi',
]


class ImageCaptionRequest(AsyncSubmitRequest):
    """图片配文接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展本接口的可选业务字段：

      - ``supplier_type``：厂商类型。接口文档（image_caption.md 第 15 行）标注
        可选值含 ``4``（腾讯）/``0``（自研）/``-7``（火山）。文档未显式指定默认，
        本实现取 ``0``（自研）作为默认值——自研是项目内 AI 能力的常规兜底厂商，
        与同 registry 的其他 vendor 字段默认取自研/项目内能力的方式一致。

    重写 ``to_payload`` 以确保 ``supplierType`` 按 camelCase 进入 payload，
    并剔除基类 ``model_dump`` 会带上的轮询控制字段占位。
    """

    supplier_type: Optional[int] = Field(0, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。"""
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


class ImageCaptionPollResponse(AsyncPollResponse):
    """图片配文任务的轮询结果。

    扩展字段 ``text_list`` 对应响应 ``data.textList``：每条配文含文字内容与
    匹配度分数。基类 ``AsyncPollResponse`` 仅展平 ``data.resultList``（图片 URL
    体系），识别不了 ``textList``，故扩展子类并通过 ``_build_result`` 提取。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    text_list: List[Dict[str, Any]] = Field(default_factory=list)


@image_tool_api_registry.register('image_caption')
class ImageCaptionApi(BaseAsyncApi):
    """图片配文的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/caption``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    Response 字段在基类 ``AsyncPollResponse`` 之外扩展 ``text_list``（提取自
    ``data.textList``），故需重写 ``_build_result`` 钩子。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/caption'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'caption'
    api_label = '图片配文'

    def execute(
        self,
        request: ImageCaptionRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ImageCaptionPollResponse:
        """类型化入口：入参指向 ``ImageCaptionRequest``，返回 ``ImageCaptionPollResponse``。

        本接口 Response 字段扩展了 ``text_list``，与基类 ``AsyncPollResponse``
        不一致，故必须类型化覆盖 execute 签名 + 重写 ``_build_result`` 注入扩展
        字段。实际流程通过 ``super().execute`` 转发。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _build_result(
        self,
        response: Any,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ImageCaptionPollResponse:
        """重写基类钩子：把 ``AsyncPollResponse`` 转成 ``ImageCaptionPollResponse``。

        基类 ``_poll`` 硬编码用 ``AsyncPollResponse.from_response`` 构造响应，
        无法识别本接口 ``data.textList`` 扩展字段。本方法从 ``data.resultList``
        各项的 ``textList`` 提取该字段，构造子类响应返回。

        注意：实际响应结构为 ``data.resultList[*].textList``（与 fileUrlList /
        fileInfoList 一样位于 resultList 项内），而非 ``data.textList``。
        """
        data = raw.get('data') or {}
        text_list_value: List[Dict[str, Any]] = []
        for item in data.get('resultList') or []:
            if not isinstance(item, dict):
                continue
            inner = item.get('textList')
            if isinstance(inner, list):
                text_list_value.extend(
                    elem for elem in inner if isinstance(elem, dict)
                )
        instance = ImageCaptionPollResponse(
            status=response.status,
            status_text=response.status_text,
            task_id=response.task_id,
            file_url_list=response.file_url_list,
            file_info_list=response.file_info_list,
            trace_id=trace_id,
            text_list=text_list_value,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance
