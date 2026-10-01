#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""person-search 专属 full/view 增量拉取循环（镜像 ``fetch_loop._run_full`` 实现逻辑，
断点落 ``op_xxxxxx/search.jsonl`` 增量、弃全局 ``search_fetch_<digest>.jsonl``）。

与 ``fetch_loop`` 的差异（仅 person-search 用，search/dynamic 不受影响）：
  - **断点 = search.jsonl 自身**：每页原子重写 ``op_xxxxxx/search.jsonl``（header
    ``lastPageAfter``=本页游标、``isFull=false``、``searchImagePersonParam`` 内嵌
    semanticInfo+recognizeFaceInfo/selectFaceList）+ 全量去重 file 行；让出后原样重跑
    读 search.jsonl 行数+``lastPageAfter`` 续拉。不用全局 ``search_fetch_<digest>.jsonl``、
    不用 ``fetch_progress.jsonl``。
  - **会话复用**：``session`` 由调用方传入（歧义轮已建 op_xxxxxx 或本轮新建），不再
    ``OrganizeSession.create()``。
  - **断点身份校验**：续拉前比对 header ``searchImagePersonParam``（剔 semanticInfo）
    与本轮参数，等值才续拉；失配（--from 换选脸/换 queryB 再澄清 = 新搜索）弃断点
    （含旧 semanticInfo）从头拉，先发 meta 提示（``data.tips`` 含新旧两组参数）。
  - 防御层（软预算让出 / OOM 上限 / 游标失效自愈 / fileId 去重 / 进度节流）与
    ``fetch_loop._run_full`` 同构——「对齐语义搜图实现逻辑」。
  - 写盘复用 ``results_store.save_results``（person 走 ``_write_person_results``，公共库零改动）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from mclaw.shared.organize.search_fetch_store import SearchFetchYield, process_elapsed
from mclaw.shared.postprocess.merge_normalize import merge_file_row_normalize
from mclaw.utils.settings import SEARCH_PROGRESS_EVERY, SEARCH_SOFT_TIME_BUDGET_SEC

from utils.config import MAX_FETCH_FILES

from services.person_search.recognize import check_person_response_success
from services.search import api_call, results_store
from services.search.errors import SearchServiceError
from services.search.param_build import SearchTask, search_param_payload
from services.search.stdout_receipt import emit_agent_note, emit_card, emit_search_results
from services.stdout_receipt import (
    Handle,
    emit_handle,
    ok_meta,
    progress_fetching,
    progress_notice,
    progress_resumed,
)

__all__ = ['run_person_search']


# ──────────────────────────── 工具 ────────────────────────────


def _normalize_cursor(value: Any) -> Optional[Any]:
    """游标归一：``None`` / 空列表 / 空串 → ``None``（= 已到末页）。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return list(value) if value else None
    if isinstance(value, str):
        return value if value.strip() else None
    return value


def _normalize_rows(resp: Any) -> List[Dict[str, Any]]:
    """响应 fileList → 16 键归一化行（复用公共库 ``merge_file_row_normalize``）。"""
    return [
        merge_file_row_normalize(f.model_dump(by_alias=True, mode='json'))
        for f in (resp.file_list or [])
    ]


def _absorb(rows: List[Dict[str, Any]], rows_unique: List[Dict[str, Any]], seen: Set[str]) -> None:
    """按 fileId 去重吸收（保留首现；空 fileId 行不去重）。"""
    for row in rows:
        fid = str(row.get('fileId') or '').strip()
        if fid and fid in seen:
            continue
        if fid:
            seen.add(fid)
        rows_unique.append(row)


def _persist(
    task: SearchTask, session: Any, rows: List[Dict[str, Any]],
    total: int, semantic_info: Optional[str], next_after: Optional[Any],
) -> None:
    """增量重写 ``op_xxxxxx/search.jsonl`` 作断点（isFull=next_after is None、lastPageAfter=next_after）。

    每页调用：杀在中途也留可续拉的 search.jsonl（header 带当前游标 + 已去重行）。
    复用 ``results_store.save_results``（person 走 ``_write_person_results``：header
    ``searchImagePersonParam``=task.param_payload+semanticInfo、file 行 ``File`` 全字段）。
    """
    results_store.save_results(
        task, rows,
        output_path=session.search_path,
        is_full=next_after is None,
        total_count=int(total or 0),
        last_page_after=next_after,
        semantic_info=semantic_info,
    )


def _load_resume(session: Any, task: SearchTask) -> Tuple[List[Dict[str, Any]], Set[str], int, Optional[str], Optional[Any], bool]:
    """读已有 search.jsonl（让出后续拉）→ (rows, seen, total, semanticInfo, page_after, resumed)。

    断点身份校验：header ``searchImagePersonParam``（剔 ``semanticInfo`` 首页冻结值）
    与本轮 ``task.param_payload`` 等值才续拉；失配（--from 换选脸/换 queryB 再澄清 =
    新搜索）先发 meta 提示（``data.tips`` 含新旧两组参数）再按无断点从头拉。
    ``session.search_header()`` 取 ``lastPageAfter``/``totalCount``/``searchImagePersonParam.semanticInfo``；
    ``session.read_search()`` 取已落盘 file 行（File → dict）。文件缺失/损坏/无参数
    快照（身份不可验）一律按新任务从头拉。
    """
    if not session.has_search():
        return [], set(), 0, None, None, False
    try:
        header = session.search_header()
        person_param = header.get('searchImagePersonParam')
        if not isinstance(person_param, dict):
            return [], set(), 0, None, None, False
        stored_param = {k: v for k, v in person_param.items() if k != 'semanticInfo'}
        if stored_param != task.param_payload:
            cur = json.dumps(task.param_payload, ensure_ascii=False)
            prev = json.dumps(stored_param, ensure_ascii=False)
            ok_meta(
                'person-search',
                say_to_user='本次搜索参数与上一轮不同，已按本次参数从头重新搜索',
                data={'tips': (
                    '本次搜索参数与上一轮不一致，已替换为本次参数并从头重新搜索。'
                    f'本次参数：{cur}；上一轮参数：{prev}'
                )},
            )
            return [], set(), 0, None, None, False
        page_after = _normalize_cursor(header.get('lastPageAfter'))
        total = int(header.get('totalCount') or 0)
        semantic_info = person_param.get('semanticInfo')
        rows_unique: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for f in session.read_search():
            row = f.model_dump(by_alias=True, mode='json')
            fid = str(row.get('fileId') or '').strip()
            if fid and fid in seen:
                continue
            if fid:
                seen.add(fid)
            rows_unique.append(row)
        resumed = bool(rows_unique or page_after is not None)
        return rows_unique, seen, total, semantic_info, page_after, resumed
    except Exception:
        # search.jsonl 损坏：宁可慢不可错，整体弃用从头拉
        return [], set(), 0, None, None, False


def _finalize_person(
    task: SearchTask, session: Any, rows: List[Dict[str, Any]],
    total: int, semantic_info: Optional[str], *, is_full: bool, last_page_after: Optional[Any],
) -> None:
    """终态：权威重写 search.jsonl（isFull + lastPageAfter）+ 交接回执 + 卡片 + agent_note + handle 尾行。

    toolresult 顺序（§2 行序定案）：searchResults 交接行（计数/提示）→ 卡片块 →
    agent_note → handle 独立尾行。
    命中 0：不产 handle（search.jsonl 不落空文件）、回执 fileCount=0、无 handle 尾行。
    """
    if not rows and not int(total):
        emit_search_results(
            search_kind=task.search_kind, query=task.receipt_query,
            keyword=task.receipt_keyword,
            file_count=0, keyword_hint=task.keyword_hint,
        )
        return
    # 权威终态重写（覆盖增量期 isFull=false 的最后一次 _persist）
    results_store.save_results(
        task, rows,
        output_path=session.search_path,
        is_full=is_full,
        total_count=int(total or 0),
        last_page_after=last_page_after,
        semantic_info=semantic_info,
    )
    dedup_count = len(rows) if is_full else None
    emit_search_results(
        search_kind=task.search_kind, query=task.receipt_query,
        keyword=task.receipt_keyword,
        file_count=int(total or 0),
        dedup_count=dedup_count, keyword_hint=task.keyword_hint,
    )
    emit_card(
        search_kind=task.search_kind, rows=rows, total=int(total or 0),
        search_param=search_param_payload(task), media_meta=None,
        semantic_info=semantic_info,
    )
    emit_agent_note()
    # handle 尾行收尾（协议行放 stdout 最后才不被头部截断；与 refine/organize 同载体）；
    # params.ambiguity=false = 终态结果无需澄清（歧义终态 handle 为 true，二值区分）
    emit_handle(Handle(id=f'{session.id}/search.jsonl', params={'ambiguity': False}))


# ──────────────────────────── 入口 ────────────────────────────


def run_person_search(task: SearchTask, *, session: Any, on_first_response=None) -> None:
    """person-search 检索入口：view=单页写盘 / full=全量翻页+增量断点。

    结果落 ``op_xxxxxx/search.jsonl``（``session`` 已由调用方建好/复用），经 stdout
    ``searchResults`` 回执交接 handle（无返回值）。``on_first_response``：首页响应钩子
    （业务成功判定后调用；merge/image 首页歧义守卫用，可抛控制流异常终止）。
    """
    if task.mode == 'view':
        _run_view(task, session=session, on_first_response=on_first_response)
        return
    _run_full(task, session=session, on_first_response=on_first_response)


def _run_view(task: SearchTask, *, session: Any, on_first_response=None) -> None:
    """view 模式：单页即终态（不翻页、不续传），落盘到 handle + 回执。

    ``isFull`` 按本页游标判定（与 full 终态同口径）：无下一页=本页即全量→``isFull=true``。
    """
    resp = api_call.call_merge_search(task, None)
    check_person_response_success(resp)
    if on_first_response is not None:
        on_first_response(resp)
    semantic_info = getattr(resp, 'semantic_info', None)
    page_rows = _normalize_rows(resp)
    # 「计数有、数据空」奇态拦截（takenAt 过滤下服务端计数与取数口径不一致）
    total_count = int(getattr(resp, 'total_count', 0) or 0)
    if not page_rows and total_count > 0:
        raise SearchServiceError(
            f'服务端返回异常：命中计数为 {total_count} 但本次未取到任何数据'
            '（接口计数与取数口径不一致）；请改用 --mode full 重新搜索'
        )
    rows_unique: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    _absorb(page_rows, rows_unique, seen)
    next_after = _normalize_cursor(getattr(resp, 'page_after', None))
    _finalize_person(
        task, session, rows_unique, total_count, semantic_info,
        is_full=next_after is None, last_page_after=next_after if next_after else None,
    )


def _run_full(task: SearchTask, *, session: Any, on_first_response=None) -> None:
    """full 模式：全量翻页 + 增量断点（每页重写 search.jsonl）+ 让出续拉。

    控制流/防御层镜像 ``fetch_loop._run_full``：软预算让出 / 游标失效自愈 / fileId 去重 /
    进度节流 / OOM 上限 / 断点身份校验（见 ``_load_resume``）。断点 = search.jsonl 自身
    （``lastPageAfter`` 跟踪游标）。
    """
    rows_unique, seen, total, semantic_info, page_after, resumed = _load_resume(session, task)
    if resumed:
        progress_resumed(len(rows_unique), total)
        if page_after is None:
            # 末页游标空 = 上一轮拉完未及终态重写 → 合并回写直接终态
            _finalize_person(
                task, session, rows_unique, total, semantic_info,
                is_full=True, last_page_after=None,
            )
            return

    is_full = True           # 默认正常翻完；OOM 截断置 False
    cap_cursor: Optional[Any] = page_after if resumed else None

    if len(rows_unique) >= MAX_FETCH_FILES:
        progress_notice(f'结果太多，已读取前 {len(rows_unique)} 条，先按这些处理～')
        is_full = False
    else:
        last_progress = len(rows_unique)
        attempts = 0
        cursor_from_checkpoint = page_after is not None
        checkpoint_retry_pending = False

        while True:
            # 软预算：每次翻页前检查（页界断点；让出 ≠ 失败，重跑即续拉）
            if process_elapsed() > SEARCH_SOFT_TIME_BUDGET_SEC:
                raise SearchFetchYield(fetched=len(rows_unique), total=total, digest='')

            attempts += 1
            try:
                resp = api_call.call_merge_search(task, page_after, semantic_info)
                check_person_response_success(resp)
                if page_after is None:
                    # 首页：抓 semanticInfo（冻结透传续页）+ 触发首页钩子（歧义守卫）
                    semantic_info = getattr(resp, 'semantic_info', None) or semantic_info
                    if on_first_response is not None:
                        on_first_response(resp)
            except (RuntimeError, SearchServiceError):
                if checkpoint_retry_pending:
                    # 游标失效自愈：续跑首试对同一游标重试仍失败 ⇒ 判过期，从头重拉
                    checkpoint_retry_pending = False
                    progress_notice('上次的进度已过期，正在从头重新搜索～')
                    rows_unique.clear()
                    seen.clear()
                    total = 0
                    page_after = None
                    cursor_from_checkpoint = False
                    continue
                if attempts == 1 and cursor_from_checkpoint:
                    # 续跑首试失败：先原地重试一次（防瞬时网络故障误伤进度），仍失败才自愈
                    checkpoint_retry_pending = True
                    continue
                raise
            checkpoint_retry_pending = False

            page_rows = _normalize_rows(resp)
            next_after = _normalize_cursor(getattr(resp, 'page_after', None))
            cap_cursor = next_after
            # total 首次非零冻结（服务端 totalCount 翻页会漂移）
            page_total = int(getattr(resp, 'total_count', 0) or 0)
            if not total and page_total:
                total = page_total

            _absorb(page_rows, rows_unique, seen)
            # 增量断点：每页重写 search.jsonl（isFull=false + lastPageAfter=next_after）
            _persist(task, session, rows_unique, total, semantic_info, next_after)

            if len(rows_unique) - last_progress >= SEARCH_PROGRESS_EVERY:
                progress_fetching(len(rows_unique), total)
                last_progress = len(rows_unique)

            if len(rows_unique) >= MAX_FETCH_FILES:
                progress_notice(f'结果太多，已读取前 {len(rows_unique)} 条，先按这些处理～')
                is_full = False
                break
            if not next_after:
                break
            page_after = next_after

    _finalize_person(
        task, session, rows_unique, total, semantic_info,
        is_full=is_full, last_page_after=cap_cursor if not is_full else None,
    )
