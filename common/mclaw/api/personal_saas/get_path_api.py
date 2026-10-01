#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询文件全路径（同步接口）。

接口路径：POST /richlifeApp/personalSaas/file/batchGetPath

单次最多 100 个 fileId，请求即返回。

入参（``GetPathRequest``）：
  | 字段 | 必填 | 类型 | 说明 |
  | fileIds | M | String[] | 文件 id 列表，最多 100 |
  | operatorId | O | Integer | 分享等三方场景操作发起者 id |

出参（``data.items`` → ``GetPathResponse.items``；需自定义解析，不使用 ``SyncResponse`` 默认展平）：
  FilePathInfo（``GetPathItem``）：
  | 字段 | 必填 | 说明 |
  | fileId | M | 文件 id |
  | idPath | M | ID 全路径，如 root:/111/222 |
  | namePath | M | 名称全路径；解析后去除 ``root:`` 前缀 |
  | type | M | file / folder |
  | errCode | O | 0000 或 null 表示成功 |
  | message | O | 失败原因 |

解析后处理：
  - ``namePath``：去除 ``root:`` 前缀后返回；
  - ``GetPathResponse.ok_items``：仅包含 ``errCode == '0000'`` 的条目。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.personal_saas import personal_saas_api_registry


__all__ = [
    'GetPathRequest',
    'GetPathItem',
    'GetPathResponse',
    'GetPathApi',
]


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class GetPathRequest(BaseModel):
    """查询文件全路径接口入参。

    本接口入参为 ``fileIds``（cloudId 体系），与媒体发送型基类 ``SyncRequest``
    （sendType/fileUrl/fileId/...）字段不重合，故直接继承 ``pydantic.BaseModel``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    file_ids: List[str] = Field(..., alias='fileIds')
    operator_id: Optional[int] = Field(None, alias='operatorId')

    @field_validator('file_ids')
    @classmethod
    def _validate_file_ids(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError('fileIds 不能为空')
        if len(v) > 100:
            raise ValueError('单次最多 100 个 fileId')
        return v

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {'fileIds': self.file_ids}
        if self.operator_id is not None:
            payload['operatorId'] = self.operator_id
        return payload


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class GetPathItem(BaseModel):
    """单条路径查询结果（``FilePathInfo``）。"""

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    file_id: str = Field('', alias='fileId')
    name_path: str = Field('', alias='namePath')
    id_path: str = Field('', alias='idPath')
    type: str = Field('')
    err_code: str = Field('0000', alias='errCode')
    message: str = Field('')


class GetPathResponse(SyncResponse):
    """路径查询响应。

    ``items`` 对应 ``data.items``。``from_response`` 已对 ``namePath`` 去除 ``root:`` 前缀。
    ``ok_items`` 返回 ``err_code == '0000'`` 的成功条目。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    items: List[GetPathItem] = Field(default_factory=list)

    @property
    def ok_items(self) -> List[GetPathItem]:
        """返回 ``err_code == '0000'`` 的成功条目。"""
        return [it for it in self.items if it.err_code == '0000']

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> 'GetPathResponse':
        """解析 ``data.items``，并对 ``namePath`` 去除 ``root:`` 前缀。"""
        data = raw.get('data') or {}
        raw_items = data.get('items') or []
        items: List[GetPathItem] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name_path = str(item.get('namePath', '')).strip()
            if name_path.startswith('root:'):
                name_path = name_path[5:]
            items.append(
                GetPathItem(
                    file_id=item.get('fileId', ''),
                    name_path=name_path,
                    id_path=item.get('idPath', ''),
                    type=item.get('type', ''),
                    err_code=item.get('errCode') or '0000',
                    message=item.get('message', ''),
                )
            )
        instance = cls(
            success=raw.get('success', False),
            code=raw.get('code', ''),
            message=raw.get('message', ''),
            trace_id=trace_id,
            items=items,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


# ──────────────────────────── API 子类 ────────────────────────────


@personal_saas_api_registry.register('get_path')
class GetPathApi(BaseSyncApi):
    """查询文件全路径的同步 API。

    路径 ``POST /richlifeApp/personalSaas/file/batchGetPath``，请求即返回最终
    结果（``items`` 含 ``fileId``/``namePath``/``idPath``/``type``），无 taskId、
    无轮询。

    Response 字段扩展了 ``items``（``List[GetPathItem]``），与基类 ``SyncResponse``
    不一致，故必须类型化 ``execute`` 签名 + 重写 ``_parse_response`` 指向
    ``GetPathResponse``。
    """

    PATH = '/richlifeApp/personalSaas/file/batchGetPath'

    api_category = 'personal_saas'
    api_label = '查询文件全路径'

    def execute(
        self,
        request: GetPathRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> GetPathResponse:
        """类型化入口：入参指向 ``GetPathRequest``，返回 ``GetPathResponse``。

        本接口 Response 字段扩展了 ``items``，与基类 ``SyncResponse`` 不一致，
        故必须类型化覆盖 execute 签名。实际流程通过 ``super().execute`` 转发，
        响应类型转换由重写的 ``_parse_response`` 完成。

        原生 ``file/getPath`` 仅接受单个
        ``fileId``，此处按 fileId 扇出后再由本类 ``_parse_response`` 组装 ``items``。
        """
        from mclaw.api.native_adapters import fanout_get_path
        if True:
            raw = fanout_get_path(
                self.host, list(request.file_ids), self._auth,
                timeout=kwargs.get('timeout', self.TIMEOUT),
                max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
                retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
                logger=self.logger,
            )
            return self._parse_response(raw, '', *args, **kwargs)
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> GetPathResponse:
        """重写基类钩子：用 ``GetPathResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``items``）。本方法改用子类的
        ``from_response``，其内部定向解析 ``data.items`` 并去 ``root:`` 前缀。
        """
        return GetPathResponse.from_response(raw, trace_id)
