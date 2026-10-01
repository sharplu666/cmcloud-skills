#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量保障断点续传编排（本技能自持，不依赖公共库续传能力）。

机制范式见 ``docs/full_fetch_resume.md``。编排链::

    本地读 search.jsonl → 完整性检测（isFull 短路 / 断点已完 / 老文件启发式）
      → 参数重建（searchKind 表，含 audio-dynamic / video-dynamic）
      → 装载断点行 + 既有文件行（fileId 去重保首现）
      → 翻页循环（页前软预算让出 / 页界断点追加 / 进度回执 / OOM 上限）
      → 游标失效自愈（首试失败试探第 1 页，成功才采纳重启）
      → 完成回写（原子替换；header 只覆盖完整性键，扩展键原样保留）

公共库仅取纯常量（页大小 / 预算 / 进度间隔）与 API 传输层（dispatcher / File
模型 / header 校验模型）——续传机制本身零公共库依赖；OOM 上限 ``MAX_FETCH_FILES``
本地定义（utils.config，与 person full / search full 同值共用）。
与 search full 链路的口径差异见 docs §8。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from mclaw.api.search_fusion import File
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.organize.presearch_paging import (
    PRESEARCH_FILE_PAGE_SIZE,
    PRESEARCH_IMAGE_FILE_PAGE_SIZE,
    PRESEARCH_IMAGE_PAGE_SIZE,
)
from mclaw.shared.organize.tools.search_results_io import (
    _HEADER_RECORDS,
    SearchResultsHeader,
)
from mclaw.utils.settings import SEARCH_PROGRESS_EVERY, SEARCH_SOFT_TIME_BUDGET_SEC

from utils.config import MAX_FETCH_FILES
from utils.helpers import atomic_write_text

from services.search_fetch.checkpoint import (
    FetchCheckpoint,
    fetch_fingerprint,
    normalize_cursor,
)
from services.stdout_receipt import progress_fetching, progress_notice, progress_resumed

__all__ = ['FetchYield', 'FullFetchRunner', 'ensure_full_results']

#: searchKind → (searchType, 参数键)。audio/video-dynamic 与 file-dynamic 同走
#: merge/file FileDynamic（header 参数快照已含 contentType）——公共库缺此映射是
#: 已记录缺口（docs §8），此处补齐。
_KIND_TO_API: Dict[str, Tuple[str, str]] = {
    'semantic-image': ('SemanticImage', 'searchImageParam'),
    'image-file': ('ImageFile', 'searchFileParam'),
    'image-dynamic': ('ImageDynamic', 'searchFileDynamicParam'),
    'file-search': ('File', 'searchFileParam'),
    'file-dynamic': ('FileDynamic', 'searchFileDynamicParam'),
    'audio-dynamic': ('FileDynamic', 'searchFileDynamicParam'),
    'video-dynamic': ('FileDynamic', 'searchFileDynamicParam'),
    'semantic-person': ('SemanticImagePerson', 'searchImagePersonParam'),
}

#: image/file-dynamic 的续拉大页口径（2026-09-15 定案：全部动态 500，
#: 与 param_build 检索页大小同口径；公共库常量仍 200，仅本技能本地覆盖）。
_DYNAMIC_LARGE_PAGE_SIZE = 500

#: searchKind → 续拉页大小（不从 header.pageSize 继承——续拉用场景大页几页拉全；
#: 2026-09-15 定案：动态全部 500，与 param_build 检索页大小同口径）。
_KIND_TO_PAGE_SIZE: Dict[str, int] = {
    'semantic-image': PRESEARCH_IMAGE_PAGE_SIZE,          # 2000
    'image-file': PRESEARCH_IMAGE_FILE_PAGE_SIZE,         # 1000
    'image-dynamic': _DYNAMIC_LARGE_PAGE_SIZE,            # 500
    'file-search': PRESEARCH_FILE_PAGE_SIZE,              # 1000
    'file-dynamic': _DYNAMIC_LARGE_PAGE_SIZE,             # 500
    'audio-dynamic': _DYNAMIC_LARGE_PAGE_SIZE,            # 500
    'video-dynamic': _DYNAMIC_LARGE_PAGE_SIZE,            # 500
    'semantic-person': 1000,  # 图文搜人（2026-09-01 用户定案续拉 1000；view/full 检索仍 50，与动态页大小解耦）
    'searchByFileIds': 1000,  # search-by-ids（同步全量落盘 isFull=true；本映射仅防误续拉兜底，正常不触发）
}


class FetchYield(Exception):
    """软预算到点的主动让出信号（断点已落盘，原样重跑同一命令即续拉）。

    **有意不继承**公共库 ``SearchFetchYield``（本机制对公共库零依赖），也**绝不
    继承** ``RuntimeError``（否则会掉进 main.py 的 RuntimeError 分支变 error 回执）。
    """

    def __init__(self, *, fetched: int, total: int) -> None:
        super().__init__(f'全量续拉让出：{fetched}/{total or "?"}')
        self.fetched = int(fetched)
        self.total = int(total or 0)


@dataclass
class _LoopResult:
    """翻页循环的出口状态（正常翻完 / OOM 截断共用）。"""

    total: int          # 展示总数（首页非零 totalCount 冻结；断点装载值延续，翻页不覆盖）
    capped: bool        # 是否命中 OOM 上限
    cp_write_ok: bool   # 断点写入是否全程成功（失败时回执已如实提示）


def _cleanup_stale_tmp(path: Path) -> None:
    """清理上次 kill -9 可能留下的回写临时残件（卫生问题，正确性无关）。"""
    try:
        for stale in path.parent.glob(f'.{path.name}.*.tmp'):
            stale.unlink(missing_ok=True)
    except OSError:
        pass


class FullFetchRunner:
    """一次「确保全量」的编排。

    状态分两层：断点持久化在 :class:`FetchCheckpoint`（跨进程），行集/游标/总数
    在实例内（单进程）。同一 handle 的下游命令须串行执行（互写断点，不加锁）。
    """

    def __init__(
        self,
        search_results_path: str | Path,
        *,
        dispatcher: Any = None,
        budget_sec: Optional[float] = None,
    ) -> None:
        self.search_path = Path(search_results_path).expanduser().resolve()
        self.checkpoint = FetchCheckpoint(self.search_path)
        self._dispatcher = dispatcher
        self._budget = (
            float(budget_sec) if budget_sec is not None
            else float(SEARCH_SOFT_TIME_BUDGET_SEC)
        )
        self._start = time.monotonic()

    # ── 对外入口 ─────────────────────────────────────────────────────────

    def run(self) -> Tuple[List[File], Dict[str, Any], bool]:
        """确保 search.jsonl 含全量；不足则续拉并回写。

        Returns:
            ``(files, header, pulled)``：全量文件列表、刷新后 header（含
            ``isFull=true``）、本次是否发生了网络拉取（False=检测短路直用）。

        Raises:
            ValueError: 文件不存在 / 非 search_results 格式 / 参数快照无法重建。
            RuntimeError: 业务失败或重试耗尽（自愈不可救时）——调用方转译。
            FetchYield: 软预算到点主动让出（断点在会话目录，重跑续拉）。
        """
        _cleanup_stale_tmp(self.search_path)
        files, header = self._read_search_file()

        # 检测 1：header isFull=true → 直接复用（零网络零输出）
        if bool(header.get('isFull')):
            if self.checkpoint.exists():
                # 回写成功后残留的断点（kill 落在「回写完成」与「删断点」之间）→ 顺手清
                self.checkpoint.clear()
            return files, header, False

        kind = str(header.get('searchKind') or '').strip()
        page_size = _KIND_TO_PAGE_SIZE.get(kind) or int(header.get('pageSize') or 0)
        fingerprint = fetch_fingerprint(header, page_size)
        progress = self.checkpoint.load(fingerprint)
        # header 首页游标（view 快照带的 lastPageAfter；老文件无此键 → None）
        header_cursor = normalize_cursor(header.get('lastPageAfter'))

        rows_unique: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def _absorb(rows: Optional[List[Dict[str, Any]]]) -> None:
            for r in rows or []:
                fid = str(r.get('fileId') or '').strip()
                if fid and fid in seen:
                    continue
                if fid:
                    seen.add(fid)
                rows_unique.append(r)

        file_rows = [f.model_dump(by_alias=True, mode='json') for f in files]

        # 检测 2：断点已完（末行游标空 = 上一轮拉完未及回写）→ 合并回写直接终态
        if progress is not None and progress.finished:
            _absorb(progress.rows)
            _absorb(file_rows)
            header_out = self._rewrite(header, rows_unique, total=progress.total)
            self.checkpoint.clear()
            return [File.model_validate(r) for r in rows_unique], header_out, False

        # 检测 3：老文件启发式（header 无 isFull 声明且行数 < pageSize → 末页即
        # 部分页视为已全）。显式 isFull=false（view 快照）绝不走此兜底——显式声明
        # 压倒启发式，否则小结果集的 view 快照会被误判已全、跳过续拉。
        h_page_size = int(header.get('pageSize') or 0)
        if header.get('isFull') is None and h_page_size and len(files) < h_page_size:
            header_out = self._rewrite(header, file_rows, total=len(files))
            return files, header_out, False

        # 需要拉全：参数快照必须可重建
        mapping = _KIND_TO_API.get(kind)
        if not mapping:
            raise ValueError(
                f'搜索结果可能不全（{len(files)} 行），且 searchKind {kind!r} 不在'
                '可续拉范围；请用 search 重新搜索落盘'
            )
        search_type, param_key = mapping
        param_dict = header.get(param_key) or {}
        if not isinstance(param_dict, dict) or not param_dict:
            raise ValueError(
                f'搜索结果可能不全（{len(files)} 行），header 参数快照 {param_key} 缺失，'
                '无法续拉；请用 search 重新搜索落盘'
            )
        payload: Dict[str, Any] = {
            'searchType': search_type,
            param_key: param_dict,
            'pageInfo': {'pageSize': page_size, 'needTotalCount': 1},
        }

        dispatcher = self._dispatcher or get_cloud_dispatcher()
        total = 0
        page_after: Optional[Any] = None
        cp_write_ok = True

        # 断点装载（有未完成断点 → 续拉；否则新建断点，header 带首页游标则种入后续拉）
        if progress is not None:
            _absorb(progress.rows)
            total = int(progress.total or 0)
            page_after = progress.cursor
            progress_resumed(progress.raw_count, total)
        else:
            cp_write_ok = self.checkpoint.initialize(fingerprint, kind)
            if not cp_write_ok:
                self._emit_checkpoint_warn(fetched=0)
        _absorb(file_rows)

        # 无断点但 header 带首页游标（view 快照）→ 既有行按断点页行种入、从该游标
        # 续拉（终态自然页序：首页行在前；semanticInfo 随参数快照整区灌回请求）。
        if progress is None and header_cursor is not None:
            seed_total = int(header.get('totalCount') or 0)
            if cp_write_ok:
                if self.checkpoint.append_page(file_rows, header_cursor, seed_total):
                    page_after = header_cursor
                    total = seed_total
                    progress_resumed(len(rows_unique), total)
                else:
                    cp_write_ok = False
                    self._emit_checkpoint_warn(fetched=len(rows_unique))

        # 续跑装载后已达 OOM 上限：无需再请求，提示后直接终态
        if len(rows_unique) >= MAX_FETCH_FILES:
            self._emit_cap_notice(len(rows_unique))
            result = _LoopResult(total=total, capped=True, cp_write_ok=cp_write_ok)
        else:
            result = self._page_loop(
                payload=payload,
                dispatcher=dispatcher,
                fingerprint=fingerprint,
                kind=kind,
                rows_unique=rows_unique,
                seen=seen,
                absorb=_absorb,
                page_after=page_after,
                total=total,
                cp_write_ok=cp_write_ok,
            )

        header_out = self._rewrite(
            header, rows_unique, total=result.total, capped=result.capped
        )
        self.checkpoint.clear()
        return [File.model_validate(r) for r in rows_unique], header_out, True

    # ── 翻页循环 ─────────────────────────────────────────────────────────

    def _page_loop(
        self,
        *,
        payload: Dict[str, Any],
        dispatcher: Any,
        fingerprint: str,
        kind: str,
        rows_unique: List[Dict[str, Any]],
        seen: set[str],
        absorb,
        page_after: Optional[Any],
        total: int,
        cp_write_ok: bool,
    ) -> _LoopResult:
        """翻页拉取到末页或 OOM 上限。

        每页前查软预算（断点永远落在完整页边界）；页成功先落断点再吸收；
        续跑首试失败触发游标失效自愈（试探第 1 页，成功才采纳重启——不多打
        一次请求；第 1 页也失败则原样上抛、断点保留）。
        """
        state = _LoopResult(total=int(total or 0), capped=False, cp_write_ok=cp_write_ok)
        last_progress = len(rows_unique)
        attempts = 0
        cursor_from_checkpoint = page_after is not None

        while True:
            # 软预算：每次翻页前检查（页界断点；让出 ≠ 失败，重跑即续拉）
            if time.monotonic() - self._start > self._budget:
                raise FetchYield(fetched=len(rows_unique), total=state.total)

            attempts += 1
            try:
                resp = self._call_search(dispatcher, payload, page_after)
                self._check_success(resp)
            except RuntimeError as exc:
                if attempts == 1 and cursor_from_checkpoint:
                    # 自愈：首试用旧游标失败 → 试探第 1 页（先不清断点）
                    try:
                        resp = self._call_search(dispatcher, payload, None)
                        self._check_success(resp)
                    except RuntimeError:
                        # 第 1 页也失败 → 网络/服务端问题：原样上抛、断点保留
                        raise exc from None
                    # 第 1 页成功 ⇒ 旧游标已过期：清断点重建、采纳本页从头继续
                    self.checkpoint.clear()
                    state.cp_write_ok = self.checkpoint.initialize(fingerprint, kind)
                    progress_notice(
                        '上次的进度已过期，正在从头重新搜索～',
                    )
                    rows_unique.clear()
                    seen.clear()
                    state.total = 0
                    page_after = None
                    cursor_from_checkpoint = False
                else:
                    raise

            page_rows, next_after = self._parse_response(resp)
            # total 首次非零冻结（2026-08-26 定案）：服务端
            # totalCount 翻页会漂移（首页 ~1.4 万、末页骤降到 ~2 千），后续页不覆盖。
            page_total = int(getattr(resp, 'total_count', 0) or 0)
            if not state.total and page_total:
                state.total = page_total
            if not self.checkpoint.append_page(page_rows, next_after, state.total):
                if state.cp_write_ok:  # 首次失败提示一次，不刷屏
                    self._emit_checkpoint_warn(fetched=len(rows_unique))
                state.cp_write_ok = False
            absorb(page_rows)

            # 进度节流：按累计条数间隔输出（口径与回执 fetched 一致）
            if len(rows_unique) - last_progress >= SEARCH_PROGRESS_EVERY:
                progress_fetching(len(rows_unique), state.total)
                last_progress = len(rows_unique)

            # OOM 硬上限：停止拉取，按现有结果终态（未含全量，回执如实标注）
            if len(rows_unique) >= MAX_FETCH_FILES:
                self._emit_cap_notice(len(rows_unique))
                state.capped = True
                return state

            # 终止判定：以 pageAfter 为空为准（空 fileList 也可能仍有下一页游标）
            if not next_after:
                return state
            page_after = next_after

    # ── API 调用与解析 ───────────────────────────────────────────────────

    @staticmethod
    def _call_search(
        dispatcher: Any,
        payload: Dict[str, Any],
        page_after: Optional[Any],
    ) -> Any:
        """按 payload + 游标发起一次 merge 搜索（公共库 dispatcher，含重试/trace）。"""
        req_payload = dict(payload)
        page_info = dict(payload.get('pageInfo') or {})
        if page_after:
            page_info['pageAfter'] = list(page_after)
        req_payload['pageInfo'] = page_info
        # searchType 反查 API：image 系走 merge_image，File/FileDynamic 走 merge_file
        if str(req_payload.get('searchType') or '') not in ('File', 'FileDynamic'):
            from mclaw.api.search_fusion.search_merge_image_api import (
                MergeImageSearchParam,
                MergeImageSearchRequest,
            )
            request = MergeImageSearchRequest(
                search_param=MergeImageSearchParam.model_validate(req_payload)
            )
            return dispatcher.search_fusion.search_merge_image(request)
        from mclaw.api.search_fusion.search_merge_file_api import (
            MergeFileSearchParam,
            MergeFileSearchRequest,
        )
        request = MergeFileSearchRequest(
            search_param=MergeFileSearchParam.model_validate(req_payload)
        )
        return dispatcher.search_fusion.search_merge_file(request)

    @staticmethod
    def _check_success(resp: Any) -> None:
        """业务失败（success=False）转自然语言异常（含 traceId，勿自动重试）。"""
        if not getattr(resp, 'success', False):
            server_msg = str(getattr(resp, 'message', '') or '').strip() or '查询失败'
            trace_id = str(getattr(resp, 'trace_id', '') or '').strip()
            trace_part = f'（traceId={trace_id}）' if trace_id else ''
            raise RuntimeError(
                f'全量续拉搜索业务失败：{server_msg}{trace_part}；'
                '请停止并交用户决策，勿自动重试'
            )

    @staticmethod
    def _parse_response(resp: Any) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        """响应 → (归一化行 dict 列表, 下一页游标)。"""
        page_rows = [
            f.model_dump(by_alias=True, mode='json')
            for f in (getattr(resp, 'file_list', None) or [])
        ]
        return page_rows, getattr(resp, 'page_after', None) or None

    @staticmethod
    def _emit_cap_notice(fetched: int) -> None:
        """OOM 硬上限提示（WARN + 停止拉取，按已获取结果落盘终态）。"""
        progress_notice(
            f'结果太多，已读取前 {fetched} 条，已按这些处理～',
        )

    def _emit_checkpoint_warn(self, *, fetched: int) -> None:
        """断点写失败提示（拉取继续；禁「宣称已保存实际没保存」的静默降级）。"""
        _ = fetched
        progress_notice(
            '进度暂存不可用，请尽量等待本次完成～',
        )

    # ── 本地读 search.jsonl ──────────────────────────────────────────────

    def _read_search_file(self) -> Tuple[List[File], Dict[str, Any]]:
        """本地读 search.jsonl → (files, header)。

        门牌两种都认（searchResultsArgs=search 命令落盘 / searchHeader=会话写）；
        fileId 去重保首现；行经 ``File.model_validate``、header 经
        ``SearchResultsHeader`` 校验——坏文件在读侧即拦，不流到续拉阶段。
        """
        if not self.search_path.is_file():
            raise ValueError(f'search_results 文件不存在或为空: {self.search_path}')
        header: Dict[str, Any] = {}
        files: List[File] = []
        seen: set[str] = set()
        found_header = False
        with self.search_path.open(encoding='utf-8') as fh:
            for line_no, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f'search_results 第 {line_no} 行不是合法 JSON: {exc}'
                    ) from exc
                if not isinstance(row, dict):
                    continue
                record = row.get('record')
                if record in _HEADER_RECORDS and not found_header:
                    header = row
                    found_header = True
                    continue
                if record != 'file':
                    continue
                file_id = str(row.get('fileId') or '').strip()
                if file_id and file_id in seen:
                    continue
                if file_id:
                    seen.add(file_id)
                row.pop('record', None)
                try:
                    files.append(File.model_validate(row))
                except ValidationError as exc:
                    raise ValueError(
                        f'search_results 第 {line_no} 行 file 记录字段不完整: {exc}'
                    ) from exc
        if not found_header:
            raise ValueError(
                f'未找到 searchResultsArgs/searchHeader 头行，请确认传入的是 '
                f'search 产的 handle: {self.search_path}'
            )
        try:
            validated = SearchResultsHeader.model_validate(header)
        except ValidationError as exc:
            raise ValueError(f'search_results header 字段不合法: {exc}') from exc
        # 校验后的 canonical（补缺省键）+ 原行扩展键原样回填（回写时保留）
        canonical = validated.to_row()
        for k, v in header.items():
            if k not in canonical:
                canonical[k] = v
        # 0 行且无续拉游标才是坏文件；0 行带 lastPageAfter = 在途部分快照
        # （2026-08-28 实证：服务端计数与取数口径不一致，首页空、计数有，
        # 续翻能取到真实数据）——放行给续拉，最终仍 0 行由调用方空语料拦截。
        if not files and normalize_cursor(canonical.get('lastPageAfter')) is None:
            raise ValueError(f'search_results 无有效文件记录: {self.search_path}')
        return files, canonical

    # ── 完成回写 ─────────────────────────────────────────────────────────

    def _rewrite(
        self,
        header: Dict[str, Any],
        rows: List[Dict[str, Any]],
        *,
        total: int,
        capped: bool = False,
    ) -> Dict[str, Any]:
        """原子回写原 jsonl：header 只覆盖完整性键，其余（含扩展键）原样保留。

        ``totalCount`` 首次落盘定死（2026-08-26 定案）：已有值永不改写（翻页
        漂移/capped 都不动数字），缺失（老文件）才补本次冻结的首次接口值；
        capped 只落 ``totalCapped=true`` 截断标记，并有意写 ``isFull=true``
        防下游反复触发续拉又反复撞顶（docs §5）。
        """
        header_out = dict(header)
        header_out['isFull'] = True
        if not int(header.get('totalCount') or 0) and total:
            header_out['totalCount'] = int(total)
        if capped:
            header_out['totalCapped'] = True
        header_out.pop('lastPageAfter', None)  # 全量完成 = 无下一页
        lines: List[str] = [json.dumps(header_out, ensure_ascii=False)]
        for r in rows:
            row = dict(r)
            row['record'] = 'file'
            lines.append(json.dumps(row, ensure_ascii=False))
        atomic_write_text(self.search_path, '\n'.join(lines) + '\n')
        return header_out


def ensure_full_results(
    search_results_path: str | Path,
    *,
    dispatcher: Any = None,
    budget_sec: Optional[float] = None,
) -> Tuple[List[File], Dict[str, Any], bool]:
    """薄封装：确保 search.jsonl 全量（不足则断点续传拉全并回写原文件）。

    Returns:
        ``(files, header, pulled)``。Raises 见 :meth:`FullFetchRunner.run`。
    """
    return FullFetchRunner(
        search_results_path, dispatcher=dispatcher, budget_sec=budget_sec
    ).run()
