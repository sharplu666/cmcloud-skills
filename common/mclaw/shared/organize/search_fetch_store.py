#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索拉取断点工件：``<plan_log>/search_fetch_<paramsDigest>.jsonl``。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mclaw.utils.settings import plan_log_dir

__all__ = [
    'EXIT_SEARCH_YIELDED',
    'PROCESS_START',
    'SearchFetchYield',
    'append_fetch_page',
    'clear_fetch_progress',
    'fetch_artifact_path',
    'fetch_params_digest',
    'load_fetch_progress',
    'process_elapsed',
    'search_yield_stdout_lines',
]

EXIT_SEARCH_YIELDED: int = 75
PROCESS_START: float = time.monotonic()


def process_elapsed() -> float:
    """返回当前进程累计运行秒数。"""
    return time.monotonic() - PROCESS_START


class SearchFetchYield(Exception):
    """搜索拉取达软预算后的主动让出信号。"""

    def __init__(
        self,
        *,
        fetched: int,
        total: int,
        digest: str,
        dynamic_start_at: Optional[str] = None,
        dynamic_end_at: Optional[str] = None,
    ) -> None:
        super().__init__(f'搜索拉取让出：{fetched}/{total or "?"}')
        self.fetched = int(fetched)
        self.total = int(total or 0)
        self.digest = str(digest)
        # 个人动态（ImageDynamic）让出时固化本次时间窗口；重跑用这两个绝对值
        # 才能复现同一 digest、命中断点（recent-days 会随 now 漂移导致 digest 失配）。
        self.dynamic_start_at = str(dynamic_start_at or '').strip() or None
        self.dynamic_end_at = str(dynamic_end_at or '').strip() or None


def fetch_params_digest(search_param: Dict[str, Any], page_size: int) -> str:
    """基于搜索参数生成断点 digest，忽略翻页游标。"""
    canonical: Dict[str, Any] = {}
    for key, value in (search_param or {}).items():
        if key == 'pageInfo' and isinstance(value, dict):
            canonical[key] = {k: v for k, v in value.items() if k != 'pageAfter'}
        else:
            canonical[key] = value
    canonical['__pageSize__'] = int(page_size or 0)
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]


def fetch_artifact_path(digest: str) -> Path:
    """返回断点工件路径。"""
    return plan_log_dir() / f'search_fetch_{str(digest or "").strip()}.jsonl'


def load_fetch_progress(digest: str) -> Tuple[List[dict], Optional[Any], int]:
    """读取断点工件，返回 (rows, cursor, total)。"""
    rows: List[dict] = []
    cursor: Optional[Any] = None
    total = 0
    try:
        text = fetch_artifact_path(digest).read_text(encoding='utf-8')
    except OSError:
        return [], None, 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            page = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(page, dict):
            continue
        page_rows = page.get('rows')
        if isinstance(page_rows, list):
            rows.extend(r for r in page_rows if isinstance(r, dict))
        cursor = page.get('pageAfter')
        total = int(page.get('total') or total or 0)
    return rows, cursor, total


def append_fetch_page(
    digest: str,
    rows: List[dict],
    page_after: Optional[Any],
    total: int,
) -> None:
    """追加一页断点数据；失败静默降级。"""
    if not str(digest or '').strip():
        return
    try:
        target = fetch_artifact_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(
                {'pageAfter': page_after, 'total': int(total or 0), 'rows': rows},
                ensure_ascii=False,
                default=str,
            ) + '\n')
            fh.flush()
    except OSError:
        pass


def clear_fetch_progress(digest: str) -> None:
    """删除已完成搜索的断点工件。"""
    try:
        fetch_artifact_path(digest).unlink(missing_ok=True)
    except OSError:
        pass


def search_yield_stdout_lines(exc: SearchFetchYield) -> List[str]:
    """生成软预算让出时需要输出到 stdout 的提示行。"""
    total_part = f'/{exc.total}' if exc.total and exc.total >= exc.fetched else ''
    yield_text = (
        f'搜索拉取已达单轮时间预算，断点已保存（{exc.fetched}{total_part} 条），'
        '正在自动续拉'
    )
    record = json.dumps({
        'record': 'progress',
        'status': 'yielded',
        'stage': 'search_fetch',
        'fetched': exc.fetched,
        'total': exc.total or None,
        'message': yield_text,
        'sayToUser': (
            f'照片较多，已读取 {exc.fetched}{total_part} 张，正在自动继续～'
            '不想等的话，直接说「就按已读取的整理」～'
        ),
    }, ensure_ascii=False)
    if exc.dynamic_start_at and exc.dynamic_end_at:
        # 个人动态：recent-days 重跑会按 now 重算窗口，digest 对不上、从头重拉。
        # 必须改用本次固化的绝对 startTime/endTime（14 位数字经 parse_date_range_value
        # 幂等回传，digest 不变 → 断点命中 → 从游标续拉）。
        hint = (
            '[INFO] 搜索让出：进度已落盘（个人动态）。本次时间窗口已固化为 '
            f'startTime={exc.dynamic_start_at} / endTime={exc.dynamic_end_at}'
            '（yyyyMMddHHmmss，精确到秒）。重跑时时间窗口必须用 '
            f'`--dynamic-start-at {exc.dynamic_start_at} '
            f'--dynamic-end-at {exc.dynamic_end_at}`——'
            '切勿改用 `--dynamic-recent-days`（会按当前时间重算，断点 digest '
            '对不上、从头重拉）；其余参数（--search-kind image-dynamic / '
            '--keyword / --dynamic-type / --bucket 等）保持完全不变，'
            '即可从断点续拉。'
        )
    else:
        hint = (
            '[INFO] 搜索让出：进度已落盘。立即以完全相同的参数重跑刚才的命令，'
            '即可从断点继续拉取。'
        )
    return [record, hint]
