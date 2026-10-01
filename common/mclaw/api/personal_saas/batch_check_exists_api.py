#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步批量检查文件是否存在（同步接口）。

接口路径：POST /richlifeApp/personalSaas/file/batchCheckExists
只查父目录直接子级，不递归。单批最多 100 条。

入参（``SubRequestEnvelope``）：
  | 字段 | 必填 | 类型 | 说明 |
  | subRequestList | M | SubRequest[] | 子请求列表，最多 100 |
  | operatorId | O | Integer | 信封级操作发起者 id（分享等三方场景） |

SubRequest：
  | 字段 | 必填 | 说明 |
  | id | M | 子请求 ID，不可重复 |
  | body | M | 见下 |

body（每条子请求）：
  | 字段 | 必填 | 说明 |
  | parentFileId | M | 父目录 id，根目录 ``'/'`` |
  | fileName | M | 待检查文件名（UTF-8，禁止 \\ / : * ? \" < > |） |
  | operatorId | O | 子请求级操作发起者 id |

出参（``SubResponseEnvelope`` → ``data.subResponseList``）：
  | 字段 | 必填 | 说明 |
  | id | M | 对应子请求 id |
  | code | M | 子响应码，0000 成功 |
  | message | M | 说明 |
  | data | M | 业务数据，见下 |

data（存在性结果）：
  | 字段 | 必填 | 说明 |
  | exist | M | 是否存在 |
  | fileId | O | exist=true 时返回 |
  | type | O | file / folder，exist=true 时返回 |
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from mclaw.api import BaseSyncApi
from mclaw.api.personal_saas import personal_saas_api_registry
from mclaw.api.personal_saas._models import SubRequestEnvelope, SubResponseEnvelope


__all__ = ['BatchCheckExistsApi']


@personal_saas_api_registry.register('batch_check_exists')
class BatchCheckExistsApi(BaseSyncApi):
    """同步接口：批量检查同名子项是否存在。"""

    PATH = '/richlifeApp/personalSaas/file/batchCheckExists'
    api_category = 'personal_saas'
    api_label = '批量检查同名子项'

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
