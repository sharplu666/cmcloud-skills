#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步批量更新文件名称（同步接口）。

接口路径：POST /richlifeApp/personalSaas/file/batchUpdate
单批最多 100 条。仅传 fileId 时只更新修改时间。

入参（``SubRequestEnvelope``）：
  | 字段 | 必填 | 类型 | 说明 |
  | subRequestList | M | SubRequest[] | 子请求列表 |

SubRequest.body：
  | 字段 | 必填 | 说明 |
  | fileId | M | 文件 id |
  | name | O | 新文件名 |
  | fileRenameMode | O | force_rename / refuse |
  | localOperatedAt | O | 本地操作时间 RFC 3339 |

出参（``SubResponseEnvelope``）：
  | 字段 | 必填 | 说明 |
  | subResponseList | M | 子响应列表 |
  | subResponseList[].data | - | 响应 data 为 null，不返回文件详情 |
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from mclaw.api import BaseSyncApi
from mclaw.api.personal_saas import personal_saas_api_registry
from mclaw.api.personal_saas._models import SubRequestEnvelope, SubResponseEnvelope


__all__ = ['BatchUpdateApi']


@personal_saas_api_registry.register('batch_update')
class BatchUpdateApi(BaseSyncApi):
    """同步接口：批量更新文件名称等属性。"""

    PATH = '/richlifeApp/personalSaas/file/batchUpdate'
    api_category = 'personal_saas'
    api_label = '批量更新文件属性'

    def execute(
        self,
        request: SubRequestEnvelope,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SubResponseEnvelope:
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self, raw: Dict[str, Any], trace_id: str, *args: Any, **kwargs: Any
    ) -> SubResponseEnvelope:
        return SubResponseEnvelope.from_response(raw, trace_id)
