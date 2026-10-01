#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI生图（异步接口）。

根据用户文本描述（可选参考图、提示词优化等）提交异步生图任务，返回 taskId +
queueOffset，需轮询 ``/richlifeApp/aiService/api/async/task/result`` 获取最终图片。
参考图可选：不传参考图（``send_type=None``）即为文生图。

能力命名 ``ai_image_generate`` 对齐文档「AI生图」与 endpoint ``/image/generate``，
厂商无关：当前 ``supplierType=7``（火山），未来扩展其他厂商无需改名。

AI生图为长耗时任务，调用方可在 ``execute(..., return_task_id=True)`` 时让超时兜底：
不再抛 ``TimeoutError``，而是返回一个 ``status=处理中``、仅 ``task_id`` 有效的
``AsyncPollResponse``，便于后续自行轮询。

接口文档：dev/docs/api/image_tool/ai_image_generate.md
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import AsyncPollResponse, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'AiImageGenerateRequest',
    'AiImageGenerateApi',
]


class AiImageGenerateRequest(BaseModel):
    """AI生图接口入参。

    本接口入参含列表型图片输入（``fileUrlList`` / ``base64List`` / ``fileIdList``）
    与两个嵌套对象（``sequentialImageGenerationOptions`` / ``optimizePromptOptions``），
    与媒体发送型异步基类 ``AsyncSubmitRequest``（单值 ``fileUrl`` / ``fileId``）字段
    不重合，故直接继承 ``pydantic.BaseModel``，并自带轮询控制字段
    （``poll_interval`` / ``poll_max_attempts``，``exclude=True``）供
    ``BaseAsyncApi._poll`` 使用。

    Attributes:
        query: 用户描述（必填）。
        send_type: 传送类型（可选）。1=url、2=base64、3=fileId；
            不传（None）表示文生图（无参考图）。
        file_url_list: ``sendType=1`` 时的图片下载地址列表。
        base64_list: ``sendType=2`` 时的 Base64 列表。
        file_id_list: ``sendType=3`` 时的 fileId 列表。
        size: 生成图像尺寸，如 ``'2048x2048'``。
        seed: 随机数种子，取值范围 [-1, 2147483647]，默认 -1。
        sequential_image_generation: ``'auto'`` 自动判断组图 / ``'disabled'`` 单张。
        sequential_image_generation_options: 仅 ``sequentialImageGeneration=auto`` 生效。
        output_format: 生成图像文件格式，可选 ``'png'`` / ``'jpeg'``。
        watermark: 是否添加“AI生成”水印。
        optimize_prompt_options: 提示词优化设置。
        supplier_type: 厂商类型，默认 ``7``（火山）。
        channel_id: 渠道 ID（可选），显式传入时才上送。
        source_task_id: 任务幂等 ID。
        poll_interval: 轮询间隔（秒），不进 payload。
        poll_max_attempts: 最大轮询次数，不进 payload。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    query: str = Field(..., alias='query')
    send_type: Optional[Literal[1, 2, 3]] = Field(None, alias='sendType')
    file_url_list: Optional[List[str]] = Field(None, alias='fileUrlList')
    base64_list: Optional[List[str]] = Field(None, alias='base64List')
    file_id_list: Optional[List[str]] = Field(None, alias='fileIdList')
    size: Optional[str] = Field(None, alias='size')
    seed: Optional[int] = Field(None, alias='seed')
    sequential_image_generation: Optional[str] = Field(None, alias='sequentialImageGeneration')
    sequential_image_generation_options: Optional[Dict[str, Any]] = Field(
        None, alias='sequentialImageGenerationOptions'
    )
    output_format: Optional[str] = Field(None, alias='outputFormat')
    watermark: Optional[bool] = Field(None, alias='watermark')
    optimize_prompt_options: Optional[Dict[str, Any]] = Field(None, alias='optimizePromptOptions')
    supplier_type: int = Field(7, alias='supplierType')
    channel_id: Optional[str] = Field(None, alias='channelId')
    source_task_id: Optional[int] = Field(None, alias='sourceTaskId')

    # 轮询控制（由 BaseAsyncApi._poll 读取，不进 payload）
    poll_interval: float = Field(2.0, exclude=True)
    poll_max_attempts: int = Field(60, exclude=True)

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        - 图生图（``send_type`` 非空）：``query`` / ``supplierType`` / ``sendType``
          必出；图片列表与 ``sendType`` 强绑定，按 ``send_type`` 值挑出对应列表
          （1→``fileUrlList``、2→``base64List``、3→``fileIdList``），
          其余两个列表字段不写入 payload。
        - 文生图（``send_type=None``）：最精简形态——``sendType=3``、三个图片
          列表均给空列表（**填空不是省略**）、``supplierType``；其余字段只在
          显式传入时才上送。
        - 嵌套对象（``sequentialImageGenerationOptions`` / ``optimizePromptOptions``）
          按原样驼峰 key 透传。
        """
        payload: Dict[str, Any] = {'query': self.query}

        if self.send_type is None:
            # 文生图：sendType=3 + 三个空图片列表 + supplierType（最精简）
            payload['sendType'] = 3
            payload['fileUrlList'] = []
            payload['fileIdList'] = []
            payload['base64List'] = []
            payload['supplierType'] = self.supplier_type
            if self.channel_id is not None:
                payload['channelId'] = self.channel_id
        else:
            # 图生图：必带 supplierType/sendType + 对应图片列表
            payload['supplierType'] = self.supplier_type
            payload['sendType'] = self.send_type
            if self.send_type == 1 and self.file_url_list is not None:
                payload['fileUrlList'] = self.file_url_list
            elif self.send_type == 2 and self.base64_list is not None:
                payload['base64List'] = self.base64_list
            elif self.send_type == 3 and self.file_id_list is not None:
                payload['fileIdList'] = self.file_id_list

        if self.size is not None:
            payload['size'] = self.size
        if self.seed is not None:
            payload['seed'] = self.seed
        if self.output_format is not None:
            payload['outputFormat'] = self.output_format
        if self.watermark is not None:
            payload['watermark'] = self.watermark
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        if self.sequential_image_generation is not None:
            payload['sequentialImageGeneration'] = self.sequential_image_generation
        if self.sequential_image_generation_options is not None:
            payload['sequentialImageGenerationOptions'] = self.sequential_image_generation_options
        if self.optimize_prompt_options is not None:
            payload['optimizePromptOptions'] = self.optimize_prompt_options
        return payload


@image_tool_api_registry.register('ai_image_generate')
class AiImageGenerateApi(BaseAsyncApi):
    """AI生图的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/generate``，轮询路径沿用
    基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（提交的 taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类或重写 ``_build_result``。

    长任务兜底：``execute(..., return_task_id=True)`` 时若轮询超时，返回一个
    ``status=处理中``、仅 ``task_id`` 有效的 ``AsyncPollResponse``，调用方可凭
    taskId 自行轮询。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/generate'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'generate'
    api_label = 'AI生图'

    def execute(
        self,
        request: AiImageGenerateRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        return_task_id: bool = False,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``AiImageGenerateRequest``，返回 ``AsyncPollResponse``。

        ``return_task_id`` 透传基类，``True`` 时超时兜底返回仅含 taskId 的响应。
        """
        return super().execute(
            request,
            *args,
            info_dict=info_dict,
            return_task_id=return_task_id,
            **kwargs,
        )
