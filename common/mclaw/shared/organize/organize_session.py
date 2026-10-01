#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整理会话（handle）—— 一个整理任务一个短 id，对应目录内放各阶段产物。

跨 skill 复用：任何「先搜索落盘 → 改维度重规划 → 提交执行 → 查询/重试」的整理流程，
都可用本类接续阶段，**模型只记短 handle，不背一长串绝对路径**。内部 ``id`` 恒为裸
``op_xxx``（供 ``open()`` 校验与目录命名）；回执里发射给 agent 的 handle 字段携带
``op_xxx/<文件>.jsonl``（与既有 ``next_steps``/``outputFile`` 同口径，仍是短相对路径），
``open()`` 收到的须为裸 id——``--from`` 解析器已先拆出文件名再传入。

设计戒律：
  - **不发 HTTP、不持鉴权/host**：纯文件编排（落盘 ``<plan_log>/<handle>/``）。接口调用走
    ``OrganizeTaskClient``；会话编排与接口调用分层，避免文件层沾染鉴权。
  - **落盘位置固定**：复用 ``mclaw.utils.settings.plan_log_dir()``（``$OPENCLAW_WORKSPACE/plan_log``），
    不读其它配置；调用方不传路径——跨阶段接续只靠 handle，不靠长路径（长路径易传错/截断）。
  - **行格式统一**：``search.jsonl`` 首行 ``{"record":"searchHeader",...}`` + ``{"record":"file",...}``
    （header 为调用方 dict 原样展开——经全量拉取回写的 header 会带 ``isFull``/``totalCount``
    等完整性字段，透传保留）；``plan.jsonl`` 首行 ``{"record":"header","planHash":...,...}`` +
    ``{"record":"row",...}``。用 ``record`` 而非 ``type`` 作行标记——``File`` 自身有 ``type``
    字段会被覆盖。
  - **原子写**：``tempfile`` + ``os.replace``，避免并发/中断留下半个 JSON。
  - **plan 行原样透传**：本类只读写 ``record:header/row`` 框架，**不解释 row 字段含义**
    （drive 的 ``targetPath`` / album 的 ``targetName`` 等由调用方与 ``to_server_rows`` 约定）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from mclaw.api.search_fusion import File
from mclaw.shared.organize.tools.search_results_io import _HEADER_RECORDS
from mclaw.utils.settings import plan_log_dir

__all__ = [
    'OrganizeSession',
    'OrganizeSessionError',
    'HANDLE_PREFIX',
    'HANDLE_RE',
]


#: handle 前缀（``op`` = organize photo/personal-cloud），与 mclaw-cloud 的 ``ph_`` 区分
HANDLE_PREFIX = 'op_'
#: handle 格式：``op_`` + 6 位十六进制
HANDLE_RE = re.compile(r'op_[0-9a-f]{6}')

_SEARCH_HEADER_RECORD = 'searchHeader'
_SEARCH_FILE_RECORD = 'file'
_PLAN_HEADER_RECORD = 'header'
_PLAN_ROW_RECORD = 'row'


class OrganizeSessionError(Exception):
    """会话不存在 / 格式不对 / 产物缺失等。"""


@dataclass
class OrganizeSession:
    """一个整理任务的本地会话目录。

    ``id`` 是短 handle（如 ``op_a3f2c1``），``dir`` 是 ``<plan_log>/<handle>/``。
    产物：``search.jsonl``（全量搜索结果，首次拷入供改维度重规划复用）、
    ``plan.jsonl``（整理预案）、``meta.json``（聚类参数快照等任意元信息）。
    """

    id: str
    dir: Path

    # ──────────────────────────── 生命周期 ────────────────────────────

    @classmethod
    def create(cls) -> 'OrganizeSession':
        """新建一个 handle 并建目录。handle 与现有目录冲突时自动重抽。"""
        import secrets

        base = plan_log_dir()
        base.mkdir(parents=True, exist_ok=True)
        while True:
            sid = HANDLE_PREFIX + secrets.token_hex(3)
            p = base / sid
            if not p.exists():
                p.mkdir()
                return cls(sid, p)

    @classmethod
    def open(cls, handle: str) -> 'OrganizeSession':
        """按 handle 打开已存在的会话；格式不符或目录不存在抛 ``OrganizeSessionError``。

        接受裸 id（``op_a3f2c1``）或带数据文件的 ``op_a3f2c1/<file>.jsonl``——回执 handle
        现携带数据文件名，此处自动剥离文件段只取会话 id（``open`` 只开会话、不碰具体
        文件；文件名白名单校验在 ``--from`` 解析器层）。返回的 ``id`` 恒为裸 ``op_xxx``。
        """
        raw = str(handle or '').strip()
        bare = raw.split('/', 1)[0]  # 容忍 op_xxx/<file>.jsonl：只取会话 id 段
        if not HANDLE_RE.fullmatch(bare):
            raise OrganizeSessionError(
                f'会话编号格式不对：{handle!r}（应形如 op_<6位编码>）'
            )
        base = plan_log_dir().resolve()
        p = (base / bare).resolve()
        # 防穿越：解析后必须在 plan_log 下
        if p.parent != base or not p.is_dir():
            raise OrganizeSessionError(f'找不到会话 {handle}')
        return cls(bare, p)

    # ──────────────────────────── search.jsonl ────────────────────────────

    @property
    def search_path(self) -> Path:
        return self.dir / 'search.jsonl'

    def has_search(self) -> bool:
        return self.search_path.is_file()

    def write_search(self, files: Iterable[File], header: Dict[str, Any]) -> int:
        """覆盖写全量搜索结果（首行 searchHeader + file 行），返回写入条数。"""
        n = 0
        with self.search_path.open('w', encoding='utf-8') as fp:
            fp.write(
                json.dumps({'record': _SEARCH_HEADER_RECORD, **header}, ensure_ascii=False) + '\n'
            )
            for f in files:
                row = f.model_dump(by_alias=True, mode='json')
                fp.write(
                    json.dumps({'record': _SEARCH_FILE_RECORD, **row}, ensure_ascii=False) + '\n'
                )
                n += 1
        return n

    def read_search(self) -> Iterator[File]:
        """读回全量 ``File``（跳过 header 行）。无 search.jsonl 抛错。"""
        if not self.search_path.is_file():
            raise OrganizeSessionError(f'会话 {self.id} 还没有搜索结果，先跑 plan 首次搜索')
        with self.search_path.open(encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get('record') == _SEARCH_FILE_RECORD:
                    row.pop('record', None)
                    yield File.model_validate(row)

    def search_header(self) -> Dict[str, Any]:
        """读 search.jsonl 首行 header；无文件返回空 dict。

        门牌兼容 ``searchHeader``（本会话 write_search 落盘）与 ``searchResultsArgs``
        （reuse 文件原样拷入）两种 —— 二者同构，读侧都认，
        避免同源 header 因 record 名不同而读不通（详见
        ``search_results_io._HEADER_RECORDS``）。
        """
        if not self.search_path.is_file():
            return {}
        with self.search_path.open(encoding='utf-8') as fp:
            first = fp.readline().strip()
        if not first:
            return {}
        row = json.loads(first)
        return row if row.get('record') in _HEADER_RECORDS else {}

    # ──────────────────────────── plan.jsonl ────────────────────────────

    @property
    def plan_path(self) -> Path:
        return self.dir / 'plan.jsonl'

    def has_plan(self) -> bool:
        return self.plan_path.is_file()

    def write_plan(
        self,
        header: Dict[str, Any],
        rows: Iterable[Dict[str, Any]],
    ) -> str:
        """覆盖写 plan（首行 header 含 planHash + row 行），返回 planHash（内容摘要）。

        ``planHash`` 对内容（header 的去重键 + 各 row）计算，与落盘路径无关——
        用于「同一份 plan 不重复提交」的去重台账。
        """
        row_list: List[Dict[str, Any]] = []
        h = hashlib.sha256()
        # header 参与哈希的键固定（避免顺序/无关字段扰动），其余键仅落盘不进哈希
        for k in ('organizeType', 'name', 'taskType', 'rootDirPath', 'renameTemplate'):
            if k in header:
                h.update(f'{k}={header[k]}'.encode('utf-8'))
        for r in rows:
            row_list.append(r)
            h.update(json.dumps(r, ensure_ascii=False, sort_keys=True).encode('utf-8'))
        plan_hash = h.hexdigest()[:16]
        lines: List[str] = [
            json.dumps(
                {'record': _PLAN_HEADER_RECORD, 'planHash': plan_hash, **header},
                ensure_ascii=False,
            )
        ]
        for r in row_list:
            lines.append(
                json.dumps({'record': _PLAN_ROW_RECORD, **r}, ensure_ascii=False)
            )
        self._atomic_write_text(self.plan_path, '\n'.join(lines) + '\n')
        return plan_hash

    def read_plan(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """读 plan → ``(header, rows)``；无 plan 或无 row 抛错。row 去掉 ``record`` 标记。"""
        if not self.plan_path.is_file():
            raise OrganizeSessionError(f'会话 {self.id} 还没有规划文件，先跑 plan')
        header: Dict[str, Any] = {}
        rows: List[Dict[str, Any]] = []
        with self.plan_path.open(encoding='utf-8') as fp:
            for line_no, raw in enumerate(fp, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise OrganizeSessionError(
                        f'plan 文件第 {line_no} 行不是合法 JSON: {exc}'
                    ) from exc
                rec = r.pop('record', None)
                if rec == _PLAN_HEADER_RECORD:
                    header = r
                elif rec == _PLAN_ROW_RECORD:
                    rows.append(r)
                # 其余 record 静默跳过（兼容调用方扩展行类型）
        if not header:
            raise OrganizeSessionError(f'plan 文件缺少 header 行：{self.plan_path}')
        if not rows:
            raise OrganizeSessionError(f'plan 文件无数据行：{self.plan_path}')
        return header, rows

    @property
    def plan_hash(self) -> str:
        """读 plan header 的 planHash；无 plan 返回空串。"""
        header, _ = self.read_plan() if self.has_plan() else ({}, [])
        return str(header.get('planHash') or '')

    # ──────────────────────────── meta.json ────────────────────────────

    @property
    def meta_path(self) -> Path:
        return self.dir / 'meta.json'

    def write_meta(self, data: Dict[str, Any]) -> None:
        """覆盖写 meta。"""
        self._atomic_write_json(self.meta_path, data)

    def read_meta(self) -> Dict[str, Any]:
        """读 meta；无文件返回空 dict。文件损坏按空处理（记 warning，不抛）。"""
        if not self.meta_path.is_file():
            return {}
        try:
            return json.loads(self.meta_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return {}

    def merge_meta(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """合并 ``data`` 进现有 meta 后落盘，返回合并后的 meta。"""
        merged = {**self.read_meta(), **(data or {})}
        self.write_meta(merged)
        return merged

    # ──────────────────────────── 工具 ────────────────────────────

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        """同目录临时文件 → ``os.replace`` 原子替换。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(text)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def _atomic_write_json(cls, path: Path, data: Any) -> None:
        cls._atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1) + '\n')
