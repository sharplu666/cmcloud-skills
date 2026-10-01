#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""断点工件（会话目录内 ``op_xxx/fetch_progress.jsonl``）的状态持久化。

机制范式见 ``docs/full_fetch_resume.md`` §3-4：
    - 工件随 handle 生命周期（与 search.jsonl 同目录），身份 = 参数指纹（首行 meta）；
    - 首行 meta（指纹/搜索类型），后续一行一页（下一页游标/总数/本页行），页界追加；
    - 读侧容错：坏 JSON 页行跳过（kill -9 半行 → 游标回退上一有效页），meta 损坏或
      指纹失配 → 整体弃用从头拉（宁可慢不可错）；
    - 写侧不静默：追加失败返回 False，由调用方写进回执（禁「宣称已保存实际没保存」）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 断点文件名（固定放 search.jsonl 同目录 = 会话目录内，随 handle 生命周期）
CHECKPOINT_FILENAME = 'fetch_progress.jsonl'

#: 断点首行 meta 的行标记
_META_RECORD = 'fetchMeta'

#: search.jsonl header 的参数快照键（指纹取其中非空者，键名一并入指纹）；
#: semantic-person 的键不进指纹会令同 kind 不同 text/selectFaces 的断点互撞串数据
_PARAM_KEYS = (
    'searchImageParam',
    'searchFileParam',
    'searchFileDynamicParam',
    'searchImagePersonParam',
)


def normalize_cursor(value: Any) -> Optional[Any]:
    """游标归一：``None`` / 空列表 / 空串 → ``None``（= 已到末页）。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return list(value) if value else None
    if isinstance(value, str):
        return value if value.strip() else None
    return value


def fetch_fingerprint(header: Dict[str, Any], full_page_size: int) -> str:
    """从 search.jsonl header 参数快照计算断点身份指纹（sha256 前 12 位）。

    canonical = {searchKind, 非空参数快照, __pageSize__}。view 落盘时参数已固化为
    绝对值（含动态场景时间窗），同 handle 重跑恒得同值、命中断点；search.jsonl
    被替换成不同搜索 → 指纹失配 → 旧断点弃用重拉。
    """
    params: Dict[str, Any] = {}
    for key in _PARAM_KEYS:
        value = header.get(key)
        if isinstance(value, dict) and value:
            # 剔除 semanticInfo（首页冻结值，首页响应落盘后才存在）：扫描侧指纹来自
            # task.param_payload（首页响应前无此键），断点 meta 指纹来自 header
            # （save_results 已注入）——不剔则 semantic-image 让出重跑的指纹扫描永不
            # 命中（person 的 _load_resume 有同款剔除先例）
            params[key] = {k: v for k, v in value.items() if k != 'semanticInfo'}
    canonical = {
        'searchKind': str(header.get('searchKind') or ''),
        'params': params,
        '__pageSize__': int(full_page_size or 0),
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]


@dataclass
class FetchProgress:
    """装载后的断点状态（多页拼接，保留原页序）。"""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    cursor: Optional[Any] = None  # 最后有效页行的 pageAfter（归一后 None=已到末页）
    total: int = 0
    finished: bool = False        # 页行非空且末行游标为空（上一轮已拉完、未及回写）

    @property
    def raw_count(self) -> int:
        """断点原始行数（去重前口径，供 resumedCount 与断点文件对账）。"""
        return len(self.rows)


class FetchCheckpoint:
    """断点状态的保存与变更：load / initialize / append_page / clear。

    一个实例对应一份 search.jsonl（断点路径 = 其同目录 ``fetch_progress.jsonl``）。
    本类不做去重与游标推进——那是编排层（``runner.FullFetchRunner``）的职责。
    """

    def __init__(self, search_path: Path) -> None:
        self.path = (
            Path(search_path).expanduser().resolve().parent / CHECKPOINT_FILENAME
        )

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self, fingerprint: str) -> Optional[FetchProgress]:
        """读断点：文件缺失 / meta 指纹失配 / 无有效页行 → ``None``（按新任务拉）。

        坏 JSON 页行跳过（kill -9 半行安全）：rows 只收有效行，游标取最后有效页行。
        """
        try:
            text = self.path.read_text(encoding='utf-8')
        except OSError:
            return None
        progress = FetchProgress()
        meta_ok = False
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get('record') or '') == _META_RECORD:
                meta_ok = str(row.get('fingerprint') or '') == str(fingerprint)
                continue
            rows = row.get('rows')
            if not isinstance(rows, list):
                continue
            progress.rows.extend(r for r in rows if isinstance(r, dict))
            progress.cursor = normalize_cursor(row.get('pageAfter'))
            progress.total = int(row.get('total') or progress.total or 0)
        if not meta_ok or not progress.rows:
            return None
        progress.finished = progress.cursor is None
        return progress

    def initialize(self, fingerprint: str, search_kind: str) -> bool:
        """建/重建断点文件（覆盖写 meta 行）；失败返回 False（拉取继续，断点不可用）。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({
                    'record': _META_RECORD,
                    'searchKind': str(search_kind or ''),
                    'fingerprint': str(fingerprint),
                    'createdAt': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                }, ensure_ascii=False) + '\n',
                encoding='utf-8',
            )
            return True
        except OSError:
            return False

    def append_page(
        self,
        rows: List[Dict[str, Any]],
        page_after: Optional[Any],
        total: int,
    ) -> bool:
        """追加一页断点数据（页界追加）；失败返回 False（调用方回执如实说明）。"""
        try:
            with self.path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(
                    {'pageAfter': page_after, 'total': int(total or 0), 'rows': rows},
                    ensure_ascii=False,
                    default=str,
                ) + '\n')
                fh.flush()
            return True
        except OSError:
            return False

    def clear(self) -> None:
        """删除断点工件（完成 / 自愈重启时）。"""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    'CHECKPOINT_FILENAME',
    'FetchCheckpoint',
    'FetchProgress',
    'fetch_fingerprint',
    'normalize_cursor',
]
