#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 写真人脸检测（同步接口）。

检测图片中是否存在可用人脸，返回 ``innerCode`` / ``innerMessage`` 标识检测
结果。**本接口为同步接口**——请求即返回最终结果，不需要轮询
``/richlifeApp/aiService/api/async/task/result``。

接口文档：dev/docs/api/ai_portrait_face_detect.md

使用场景：
  - 作为 ``image_comic_style``（AI 漫画风）的前置检测：``innerCode == '0000'``
    才继续执行漫画风转换，否则终止。
  - 也可独立调用，用于判断图片是否含可用人脸。

响应说明：
  本接口响应 ``data`` 含 ``existFace`` / ``innerCode`` / ``innerMessage`` /
  ``taskId`` 四个业务字段。基类 ``SyncResponse.from_response`` 默认展平
  ``data`` 嵌套层，子类业务字段（带 alias）会被自动填充；但 ``BaseSyncApi``
  硬编码用基类 ``SyncResponse.from_response`` 解析，识别不了子类，故需重写
  ``_parse_response`` 指向本接口的 ``AiPortraitFaceDetectResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'AiPortraitFaceDetectRequest',
    'AiPortraitFaceDetectResponse',
    'AiPortraitFaceDetectApi',
]


class AiPortraitFaceDetectRequest(SyncRequest):
    """AI 写真人脸检测接口入参。

    在 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）基础上，
    扩展本接口的业务字段：

      - ``is_mask``：是否做人脸遮挡检测，默认 ``False``。
      - ``is_anime``：是否做人脸动漫化判断，默认 ``False``。
      - ``is_exposed``：是否做人脸涉敏判断，默认 ``False``。
      - ``is_multifaces``：是否做多人脸检测，默认 ``False``。
      - ``supplier_type``：厂商类型，可选。接口文档标注自研（``0``）。

    重写 ``to_payload`` 以确保驼峰字段名进入 payload，并按 ``sendType`` 选择
    ``fileUrl`` 或 ``fileId``，同时在 ``supplier_type`` 为 ``None`` 时省略
    该字段（不发送 ``null``）。
    """

    is_mask: bool = Field(False, alias='isMask')
    is_anime: bool = Field(False, alias='isAnime')
    is_exposed: bool = Field(False, alias='isExposed')
    is_multifaces: bool = Field(False, alias='isMultifaces')
    supplier_type: Optional[int] = Field(None, alias='supplierType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``
        已能输出大部分字段，但 ``supplier_type`` 为 ``None`` 时应省略（不发送
        ``null``），故显式构造 payload 以精确控制字段集合与 sendType 条件字段。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext,
            'isMask': self.is_mask,
            'isAnime': self.is_anime,
            'isExposed': self.is_exposed,
            'isMultifaces': self.is_multifaces,
        }
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        if self.supplier_type is not None:
            payload['supplierType'] = self.supplier_type
        return payload


class AiPortraitFaceDetectResponse(SyncResponse):
    """AI 写真人脸检测接口出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``exist_face``：是否存在可用人脸
      - ``inner_code``：算法返回码（``'0000'`` 表示通过）
      - ``inner_message``：返回码说明
      - ``task_id``：任务ID（用于排查）

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故这些字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    exist_face: bool = Field(False, alias='existFace')
    inner_code: str = Field('', alias='innerCode')
    inner_message: str = Field('', alias='innerMessage')
    task_id: Optional[str] = Field(None, alias='taskId')


@image_tool_api_registry.register('ai_portrait_face_detect')
class AiPortraitFaceDetectApi(BaseSyncApi):
    """AI 写真人脸检测的同步 API。

    路径 ``POST /richlifeApp/aiService/api/image/detect/face``，请求即返回最终
    结果（``existFace``/``innerCode``/``innerMessage``/``taskId``），无 ``taskId``
    轮询。

    Response 字段扩展了 ``exist_face``/``inner_code``/``inner_message``/
    ``task_id``，与基类 ``SyncResponse`` 不一致，故必须类型化 ``execute`` 签名 +
    重写 ``_parse_response`` 指向 ``AiPortraitFaceDetectResponse``。
    """

    PATH = '/richlifeApp/aiService/api/image/detect/face'

    api_category = 'detect'
    api_label = 'AI写真人脸检测'

    def execute(
        self,
        request: AiPortraitFaceDetectRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AiPortraitFaceDetectResponse:
        """类型化入口：入参指向 ``AiPortraitFaceDetectRequest``，返回
        ``AiPortraitFaceDetectResponse``。

        本接口 Response 字段扩展了 ``exist_face``/``inner_code`` 等，与基类
        ``SyncResponse`` 不一致，故必须类型化覆盖 execute 签名。实际流程通过
        ``super().execute`` 转发，响应类型转换由重写的 ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> AiPortraitFaceDetectResponse:
        """重写基类钩子：用 ``AiPortraitFaceDetectResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``exist_face``/``inner_code``/...）。
        本方法改用子类的 ``from_response``，其内部默认展平 ``data`` 嵌套层后，
        子类字段按 alias 自动填充。
        """
        return AiPortraitFaceDetectResponse.from_response(raw, trace_id)
