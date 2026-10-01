#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宝宝时光机（异步接口）。

根据宝宝当前照片与性别，预测不同年龄段的样貌变化。提交后返回
taskId + queueOffset，需轮询 ``/richlifeApp/aiService/api/async/task/result``
获取最终结果。

参数约束（服务端校验，本客户端不强制）：
  - gender=2（未知）时仅接受 ageGroup=0（未出生）
  - gender=0/1 时 ageGroup 可选 1（0-5岁）/ 2（6-15岁）

接口文档：dev/docs/api/baby_time_machine.md
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from mclaw.api import AsyncPollResponse, AsyncSubmitRequest, BaseAsyncApi
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'BabyTimeMachineRequest',
    'BabyTimeMachineApi',
]


class BabyTimeMachineRequest(AsyncSubmitRequest):
    """宝宝时光机接口入参。

    在 ``AsyncSubmitRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId
    + 轮询控制字段）基础上，扩展本接口三个业务字段：
      - ``gender``：性别（必填），``0`` 女性 / ``1`` 男性 / ``2`` 未知
      - ``age_group``：年龄段（可选），``1`` 0-5岁 / ``2`` 6-15岁 / ``0`` 未出生
        注意：gender=2（未知）时仅接受 ageGroup=0；本客户端不强制约束，
        由服务端校验，调用方需自行保证传入合法组合。
      - ``supplier_type``：厂商类型，默认 ``8``（美图）

    重写 ``to_payload`` 以确保 gender/ageGroup/supplierType 按 camelCase
    进入 payload，且不含轮询控制字段。
    """

    gender: int = Field(..., alias='gender')
    age_group: Optional[int] = Field(None, alias='ageGroup')
    supplier_type: Optional[int] = Field(8, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        重新构造 payload 而非沿用基类 ``model_dump(by_alias=True,
        exclude_none=True)``，以排除 exclude=True 的轮询控制字段，
        同时确保 fileUrl/fileId 按 sendType 二选一填充。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext.lower().lstrip("."),
            'gender': self.gender,
            'supplierType': self.supplier_type,
        }
        if self.age_group is not None:
            payload['ageGroup'] = self.age_group
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        return payload


@image_tool_api_registry.register('baby_time_machine')
class BabyTimeMachineApi(BaseAsyncApi):
    """宝宝时光机的异步 API。

    提交路径 ``/richlifeApp/aiService/api/image/edit/babyTimeMachine``，
    轮询路径沿用基类默认的 ``/richlifeApp/aiService/api/async/task/result``。

    响应字段（taskId/queueOffset + 轮询后的 status/file_url_list）与基类
    ``AsyncPollResponse`` 完全一致，无需扩展 Response 子类。
    """

    SUBMIT_PATH = '/richlifeApp/aiService/api/image/edit/babyTimeMachine'
    # POLL_PATH 沿用基类默认（aiService/api/async/task/result）

    api_category = 'edit'
    api_label = '宝宝时光机'

    def execute(
        self,
        request: BabyTimeMachineRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncPollResponse:
        """类型化入口：入参指向 ``BabyTimeMachineRequest``，返回 ``AsyncPollResponse``。

        本接口 Response 字段与基类 ``AsyncPollResponse`` 一致，无需扩展 Response
        子类或重写 ``_build_result``。仅类型化 execute 签名后转发基类实现。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)
