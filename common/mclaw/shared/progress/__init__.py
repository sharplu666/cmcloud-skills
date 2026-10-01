#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进度回执共享层：统一的 ``record=progress`` 数据格式。

各 skill / 各阶段需要向用户打出进度时，统一用 :class:`ProgressRecord` 构造，
再由调用方 ``print(ProgressRecord(...).to_json_line(), flush=True)`` 直接输出——
**不封装额外的 emit 函数**，每个阶段各自负责打印。
"""

from mclaw.shared.progress.record import ProgressRecord

__all__ = ['ProgressRecord']
