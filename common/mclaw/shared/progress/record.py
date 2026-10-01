#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进度回执数据模型（跨 skill 共用格式）。

约定格式::

    {"record": "progress", "status": "<阶段状态>", "stage": "<阶段名>", "sayToUser": "<给人看的话>"}

- ``record`` 固定 ``'progress'``；
- ``status`` 该阶段状态（如 ``'finish'``）；
- ``stage`` 阶段名（如 ``'resultPreview'`` / ``'taskSubmitted'``）；
- ``sayToUser`` 给人看的一句话。

调用方自行 ``print(ProgressRecord(...).to_json_line(), flush=True)`` 直接输出，
**无需**也**不应**再封装 emit 函数——每个阶段各自打印。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ProgressRecord:
    """进度回执（``record=progress``）。"""

    status: str
    stage: str
    say_to_user: str
    record: str = 'progress'

    def to_json_line(self) -> str:
        """序列化为单行 JSON（``sayToUser`` 按回执约定用驼峰）。"""
        return json.dumps(
            {
                'record': self.record,
                'status': self.status,
                'stage': self.stage,
                'sayToUser': self.say_to_user,
            },
            ensure_ascii=False,
        )
