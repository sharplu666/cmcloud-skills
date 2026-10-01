#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图像矫正（同步接口）。

对图像及文档进行铺平、扭曲矫正。**本接口为同步接口**——请求即返回最终结果
（``requestId``/``resultType``/``fileId``/``fileUrl``/``base64``/``fileInfo``），
不需要轮询 ``/async/task/result``。

接口文档：dev/docs/api/image_shift.md

响应说明：
  本接口响应非标准（返回 ``requestId``/``resultType``/``fileId``/``fileUrl``/
  ``base64``/``fileInfo``，而非异步接口的 ``taskId``+``queueOffset``），故扩展
  ``SyncResponse`` 增加业务字段。基类 ``SyncResponse.from_response`` 默认展平
  ``data`` 嵌套层，子类业务字段（带 alias）会被自动填充；但 ``BaseSyncApi``
  硬编码用基类 ``SyncResponse.from_response`` 解析，识别不了子类，故需重写
  ``_parse_response`` 指向本接口的 ``ImageShiftResponse``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.image_tool import image_tool_api_registry


__all__ = [
    'ImageShiftRequest',
    'ImageShiftResponse',
    'ImageShiftApi',
]


class ImageShiftRequest(SyncRequest):
    """图像矫正接口入参。

    在 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）基础上，
    扩展本接口的业务字段：

      - ``supplier_type``：厂商类型，**必填（M）**。可选值 ``0``（自研）、
        ``2``（阿里）、``9``（网易）。
      - ``angle_detection``：是否进行方向矫正（O），默认 ``False``。AI 相机时
        需传 ``True``，仅支持文档类图像。
      - ``dewarp``：是否纠正文档扭曲（O），默认 ``False``。AI 相机时需传
        ``True``，仅支持文档类图像。
      - ``parent_dir_id``：个人云父目录 Id（O）。有值则将算法结果保存到该目录，
        供会话目录归档使用。
      - ``file_name``：保存后的文件名（O）。有传则以端侧为准，没传则后端
        随机生成。

    接口文档其余字段（``channelId``/``location``）为可选（O），当前测试
    （``image_shift/scripts/test.sh``）未覆盖，故此处不建模，保持入参与
    测试覆盖一致。后续如需扩展分支，再补字段。

    重写 ``to_payload`` 以确保驼峰字段名进入 payload，并按 ``sendType`` 选择
    ``fileUrl`` 或 ``fileId``。
    """

    supplier_type: int = Field(..., alias='supplierType')
    angle_detection: bool = Field(False, alias='angleDetection')
    dewarp: bool = Field(False, alias='dewarp')
    parent_dir_id: Optional[str] = Field(None, alias='parentDirId')
    file_name: Optional[str] = Field(None, alias='fileName')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        基类 ``to_payload`` 做 ``model_dump(by_alias=True, exclude_none=True)``
        已能输出大部分字段，但会按 ``sendType`` 同时保留 ``fileUrl`` 与 ``fileId``
        中的非空项。为确保只输出与发送方式匹配的字段（与服务端约定一致），
        这里显式构造 payload。
        """
        payload: Dict[str, Any] = {
            'sendType': self.send_type,
            'imageExt': self.image_ext.lower().lstrip("."),
            'supplierType': self.supplier_type,
            'angleDetection': self.angle_detection,
            'dewarp': self.dewarp,
        }
        if self.send_type == 1:
            payload['fileUrl'] = self.file_url
        else:
            payload['fileId'] = self.file_id
        if self.source_task_id is not None:
            payload['sourceTaskId'] = self.source_task_id
        if self.parent_dir_id:
            payload['parentDirId'] = self.parent_dir_id
        if self.file_name:
            payload['fileName'] = self.file_name
        return payload


class ImageShiftResponse(SyncResponse):
    """图像矫正接口出参（同步返回，非标准结构）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``request_id``：请求ID（M）
      - ``result_type``：传送类型（M），1—url / 2—base64 / 3—文件信息
      - ``file_id_out``：结果文件ID（O，alias ``fileId``）
      - ``file_url``：结果图像下载地址（O）
      - ``base64``：结果图片Base64（O）
      - ``file_info``：文件信息（O）

    基类 ``SyncResponse.from_response`` 已展平 ``data`` 嵌套层，故这些字段
    会被 ``model_validate`` 按 alias 自动填充，**无需重写 ``from_response``**。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    request_id: Optional[str] = Field(None, alias='requestId')
    result_type: Optional[int] = Field(None, alias='resultType')
    file_id_out: Optional[str] = Field(None, alias='fileId')
    file_url: Optional[str] = Field(None, alias='fileUrl')
    base64: Optional[str] = Field(None, alias='base64')
    file_info: Optional[Dict[str, Any]] = Field(None, alias='fileInfo')


@image_tool_api_registry.register('image_shift')
class ImageShiftApi(BaseSyncApi):
    """图像矫正的同步 API。

    路径 ``POST /richlifeApp/aiService/api/image/edit/shift``，请求即返回最终
    结果（``requestId``/``resultType``/``fileId``/...），无 ``taskId``、无轮询。

    Response 字段扩展了 ``request_id``/``result_type``/``file_id_out``/``file_url``/
    ``base64``/``file_info``，与基类 ``SyncResponse`` 不一致，故必须类型化
    ``execute`` 签名 + 重写 ``_parse_response`` 指向 ``ImageShiftResponse``。
    """

    PATH = '/richlifeApp/aiService/api/image/edit/shift'

    api_category = 'edit'
    api_label = '图像矫正'

    def execute(
        self,
        request: ImageShiftRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ImageShiftResponse:
        """类型化入口：入参指向 ``ImageShiftRequest``，返回 ``ImageShiftResponse``。

        本接口 Response 字段扩展了 ``request_id``/``result_type``/``file_id_out``
        等，与基类 ``SyncResponse`` 不一致，故必须类型化覆盖 execute 签名。
        实际流程通过 ``super().execute`` 转发，响应类型转换由重写的
        ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ImageShiftResponse:
        """重写基类钩子：用 ``ImageShiftResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``request_id``/``result_type``/...）。
        本方法改用子类的 ``from_response``，其内部默认展平 ``data`` 嵌套层后，
        子类字段按 alias 自动填充。
        """
        return ImageShiftResponse.from_response(raw, trace_id)

    def _build_result_dict(
        self,
        response: ImageShiftResponse,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """终态日志脱敏：将冗长的签名下载 URL 屏蔽为 ``***``。

        本接口结果图经 ``resultType=3`` 返回时，``data.fileInfo.content`` 与
        ``data.fileInfo.thumbnailUrl`` 是数百字符的 S3 预签名 URL，完整打印会
        污染日志（``resultType=1`` 时 ``data.fileUrl`` 同理，``=2`` 时
        ``data.base64`` 是整段图片 Base64）。这里返回一份精简副本，把这些字段
        替换为 ``***``，仅作用于日志展示，``response.raw`` / 返回值不受影响。

        风格对齐 ``search_fusion`` 的 ``redact_search_result``：浅拷贝外壳，
        不修改入参 ``response.raw``。
        """
        raw = response.raw
        if not isinstance(raw, dict):
            return raw
        data = raw.get('data')
        if not isinstance(data, dict):
            return raw

        _REDACT = '***'

        def _redact_map(d: Dict[str, Any], keys: tuple) -> Dict[str, Any]:
            if not any(k in d for k in keys):
                return d
            return {k: (_REDACT if k in keys else v) for k, v in d.items()}

        _URL_KEYS = ('content', 'thumbnailUrl', 'fileUrl')
        _B64_KEYS = ('base64',)

        new_data = _redact_map(data, _URL_KEYS + _B64_KEYS)
        file_info = new_data.get('fileInfo')
        if isinstance(file_info, dict):
            new_data = {**new_data, 'fileInfo': _redact_map(file_info, _URL_KEYS)}
        return {**raw, 'data': new_data}
