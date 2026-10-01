#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宝宝长相预测（异步接口）。

根据父亲和母亲的照片，预测未出生宝宝在不同年龄段（0/3/6/12/18）和性别
（0=女，1=男）下的样貌。提交后返回 ``taskId`` + ``queueOffset``，需轮询
``/richlifeApp/aiService/api/async/task/result`` 获取结果。

接口文档：dev/docs/api/baby_face_prediction.md

特殊点：
  - 请求体使用 **father / mother 嵌套 ImageParam 对象**，与 ``AsyncSubmitRequest``
    的扁平 sendType/fileUrl/fileId 结构不兼容，故 Request 直接继承
    ``pydantic.BaseModel``，自带轮询控制字段供 ``BaseAsyncApi._poll`` 使用。
  - 提交路径含拼写 ``gaby``（非 ``baby``），按接口文档原样保留。

参考实现：
  - ``mclaw.api/operation/batch_move_files_api.py``（不继承 AsyncSubmitRequest
    的异步接口，直接继承 BaseModel + poll_interval/poll_max_attempts）
  - ``mclaw.api/image_tool/ai_expand_image_api.py``（嵌套 BaseModel
    ``ExpandRatio`` 的序列化模式）
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import AsyncPollResponse, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'ImageParam',
    'BabyFacePredictionRequest',
    'BabyFacePredictionApi',
]


class ImageParam(BaseModel):
    """嵌套图片输入参数（father / mother 各一份）。

    对应接口文档 ``ImageParam`` 结构：``sendType`` + ``fileUrl`` / ``fileId`` /
    ``base64``（互斥，按 ``sendType`` 选择）+ ``imageExt``。

    Attributes:
        send_type: 1=url（必填 file_url），3=fileId/base64（可传 file_id 或 base64）。
        file_url: 图片 URL，``send_type=1`` 时必填。
        file_id: 云盘文件 id，``send_type=3`` 时可传。
        file_base64: 图片 base64，``send_type=3`` 时可传（与 file_id 互斥）。
        image_ext: 图片扩展名（如 ``jpg``），必填。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    send_type: int = Field(..., alias='sendType')
    file_url: Optional[str] = Field(None, alias='fileUrl')
    file_id: Optional[str] = Field(None, alias='fileId')
    file_base64: Optional[str] = Field(None, alias='base64')
    image_ext: Optional[str] = Field(None, alias='imageExt')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 camelCase 字段。

        - ``send_type=1``：输出 ``fileUrl`` + ``imageExt``
        - ``send_type=3``：输出 ``fileId``（若提供）或 ``base64``（若提供）+ ``imageExt``
        """
        payload: Dict[str, Any] = {'sendType': self.send_type}
        if self.send_type == 1:
            if self.file_url is not None:
                payload['fileUrl'] = self.file_url
        else:
            if self.file_id is not None:
                payload['fileId'] = self.file_id
            if self.file_base64 is not None:
                payload['base64'] = self.file_base64
        if self.image_ext is not None:
            payload['imageExt'] = self.image_ext.lower().lstrip(".")
        return payload


class BabyFacePredictionRequest(BaseModel):
    """宝宝长相预测接口入参。

    本接口使用 father/mother 嵌套 ``ImageParam`` 结构，与媒体发送型异步基类
    ``AsyncSubmitRequest``（扁平 sendType/fileUrl/fileId）字段不重合，故直接
    继承 ``pydantic.BaseModel``，自带 ``poll_interval`` / ``poll_max_attempts``
    （``exclude=True``）供 ``BaseAsyncApi._poll`` 读取。

    Attributes:
        father: 父亲图片输入参数。
        mother: 母亲图片输入参数。
        gender: 宝宝性别：``0`` 女，``1`` 男。
        age: 预测年龄：``0`` / ``3`` / ``6`` / ``12`` / ``18``。
        supplier_type: 厂商类型，可选。
        source_task_id: 任务幂等 id，可选。
        poll_interval: 轮询间隔（秒），不进 payload。
        poll_max_attempts: 最大轮询次数，不进 payload。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    father: ImageParam
    mother: ImageParam
    gender: int
    age: int

    supplier_type: Optional[int] = Field(None, alias='supplierType')
    source_task_id: Optional[int] = Field(None, alias='sourceTaskId')

    # 轮询控制（由 BaseAsyncApi._poll 读取，不进 payload）
    poll_interval: float = Field(2.0, exclude=True)
    poll_max_attempts: int = Field(60, exclude=True)

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰 + father/mother 嵌套对象）。

        嵌套 ``ImageParam`` 通过其自身的 ``to_payload()`` 序列化为 camelCase
        dict；顶层业务字段手工拼装，避免带入 exclude=True 的轮询占位字段。
        """
        payload: Dict[str, Any] = {
            'father': self.father.to_payload(),
            'mother': self.mother.to_payload(),
            'gender': self.gender,
            'age': self.age,
        }
        if self.supplier_type is not None:
            payload['supplierType'] = self.supplier_type
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('baby_face_prediction')
class BabyFacePredictionApi(BaseAsyncApi):
    """宝宝长相预测的异步 API。

    提交路径含拼写 ``gaby``（接口文档原文如此，按 ``gabyGrowthPrediction``
    保留）；轮询路径沿用基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类或重写 ``_build_result``。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/edit/gabyGrowthPrediction'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'edit'
    api_label = '宝宝长相预测'

    def execute(
        self,
        request: BabyFacePredictionRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``BabyFacePredictionRequest``，返回 ``AsyncPollResponse``。

        本接口 Request 字段（嵌套 ImageParam）与基类 ``AsyncSubmitRequest``
        不一致，故必须类型化覆盖 execute 签名；Response 字段与基类
        ``AsyncPollResponse`` 一致，无需扩展或重写 ``_build_result``。
        实际流程通过 ``super().execute`` 转发。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
