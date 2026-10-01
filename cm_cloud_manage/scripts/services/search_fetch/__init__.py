#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_fetch 子包：全量保障断点续传（本技能自持，不依赖公共库续传能力）。

    - checkpoint.py  断点状态持久化（会话目录内 fetch_progress.jsonl）
    - runner.py      编排（完整性检测 / 翻页 / 让出 / 自愈 / 原子回写）

机制范式与协议见 ``docs/full_fetch_resume.md``。
"""

from services.search_fetch.checkpoint import (  # noqa: F401
    CHECKPOINT_FILENAME,
    FetchCheckpoint,
    FetchProgress,
    fetch_fingerprint,
)
from services.search_fetch.runner import (  # noqa: F401
    FetchYield,
    FullFetchRunner,
    _KIND_TO_PAGE_SIZE,
    ensure_full_results,
)

__all__ = [
    'CHECKPOINT_FILENAME',
    'FetchCheckpoint',
    'FetchProgress',
    'fetch_fingerprint',
    'FetchYield',
    'FullFetchRunner',
    '_KIND_TO_PAGE_SIZE',
    'ensure_full_results',
]
