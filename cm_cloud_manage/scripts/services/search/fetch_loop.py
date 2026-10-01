#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索编排主循环（全技能唯一一份）。

``--mode``（D20）分流::

    view（默认，单页快速返回）
      → 单次 api_call（页大小=场景常量）→ 去重 → 落单页快照（本页游标空则
        isFull=true，否则 false）→ emit searchResults 回执（view/full 同形：带
        handle+counts）+ 卡片 + agent_note；不进翻页循环、不碰断点，让出不会发生。

    full（全量拉取）
      首页取数落盘（与 view 同款 _fetch_first_page：isFull=false 部分快照，header
        带首页游标与 totalCount）
        → ensure_full_results 就地续拉补全（services.search_fetch：断点 =
          op_xxx/fetch_progress.jsonl，与 refine/organize 同机制——页界追加 /
          软预算让出 / 游标失效自愈 / OOM 硬上限全在 runner 内）
        → 终态发射（计数取自续拉回写后的 header）。
      让出后「原样重跑同一命令」：_find_resumable_session 用参数指纹扫 plan_log
      命中会话 → 跳过首页直接进续拉（断点游标起，此时不触发首页钩子——与翻页
      时代续跑语义一致）。

终态 toolresult 顺序（view/full 一致，card_toolresult_design.md §2）：
searchResults 回执 → 卡片块 → agent_note（full 前面可能有多条 progress，由
runner 发出）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mclaw.shared.organize.organize_session import (
    HANDLE_RE,
    OrganizeSession,
    OrganizeSessionError,
)
from mclaw.shared.postprocess.merge_normalize import merge_file_row_normalize
from mclaw.utils.settings import plan_log_dir

from services.search import api_call, results_store
from services.search.errors import SearchServiceError
from services.search.param_build import SearchTask, search_param_payload
from services.search.stdout_receipt import (
    emit_agent_note,
    emit_card,
    emit_search_results,
)
from services.search_fetch import FetchYield, _KIND_TO_PAGE_SIZE, ensure_full_results
from services.search_fetch.checkpoint import CHECKPOINT_FILENAME, fetch_fingerprint
# handle 行走公共层 emit_handle（§2 行序定案：协议行尾置防头部截断；与
# refine/organize 同载体）
from services.stdout_receipt import Handle, emit_handle


@dataclass(frozen=True)
class _FirstPage:
    """首页取数结果（view 唯一页 / full 首页共用；只装数据，不含落盘与发射）。"""

    rows: List[Dict[str, Any]]        # 归一化 + fileId 去重后的行
    total: int                        # 接口 totalCount 原样
    next_after: Optional[List[Any]]   # 下一页游标（None=本页即全量）
    semantic_info: Optional[str]      # SemanticImage 首页语义理解串（其余场景 None）


def _normalize_page_rows(resp: api_call.MergeSearchResponse) -> List[Dict[str, Any]]:
    """响应 fileList → 16 键归一化行（复用公共库 merge_file_row_normalize）。"""
    return [
        merge_file_row_normalize(f.model_dump(by_alias=True, mode='json'))
        for f in (resp.file_list or [])
    ]


def _check_business_success(resp: api_call.MergeSearchResponse) -> None:
    """业务失败（success=False / code 非 0000）转自然语言回执异常。"""
    if not getattr(resp, 'success', False) or str(getattr(resp, 'code', '')) != '0000':
        server_msg = str(getattr(resp, 'message', '') or '').strip() or '查询失败'
        trace_id = str(getattr(resp, 'trace_id', '') or '').strip()
        trace_part = f'（traceId={trace_id}）' if trace_id else ''
        raise SearchServiceError(
            f'服务端错误：{server_msg}{trace_part}；请停止并交用户决策，勿自动重试'
        )


def _absorb_page_rows(
    rows: List[Dict[str, Any]],
    rows_unique: List[Dict[str, Any]],
    seen: set[str],
) -> int:
    """按 fileId 去重吸收一页行（保留首现；空 fileId 行不去重），返回新增条数。"""
    added = 0
    for row in rows:
        file_id = str(row.get('fileId') or '').strip()
        if file_id and file_id in seen:
            continue
        if file_id:
            seen.add(file_id)
        rows_unique.append(row)
        added += 1
    return added


def _fetch_first_page(task: SearchTask, on_first_response=None) -> _FirstPage:
    """取首页一次（pageAfter=None）：业务判定 → 首页钩子 → 归一化 → 去重吸收。

    只取数：不落盘、不发任何回执行；奇态拦截归调用方（仅 view 拦「计数有、
    数据空」）。首页响应的 semanticInfo（仅 SemanticImage 返回）抓取后冻结透传。
    """
    resp = api_call.call_merge_search(task, None)
    _check_business_success(resp)
    if on_first_response is not None:
        on_first_response(resp)  # 首页钩子（person-search 歧义守卫；None=无操作）
    rows_unique: List[Dict[str, Any]] = []
    _absorb_page_rows(_normalize_page_rows(resp), rows_unique, set())
    return _FirstPage(
        rows=rows_unique,
        total=int(resp.total_count or 0),
        next_after=resp.page_after or None,
        semantic_info=getattr(resp, 'semantic_info', None),
    )


def _open_and_save(
    task: SearchTask,
    rows: List[Dict[str, Any]],
    total: int,
    *,
    is_full: bool,
    last_page_after: Any,
    semantic_info: Optional[str],
) -> OrganizeSession:
    """终态落盘半段：建 op_xxx 会话 + 原子写 search.jsonl，返回会话（不发射）。"""
    # search 直接产 handle：建 op_xxx 目录，结果落进 search.jsonl（尾行 handle=op_xxx/search.jsonl）
    try:
        session = OrganizeSession.create()
    except OrganizeSessionError as exc:
        raise SearchServiceError(f'建立搜索会话失败：{exc}；请停止并交用户决策') from exc
    results_store.save_results(
        task, rows,
        output_path=session.search_path, is_full=is_full,
        total_count=total, last_page_after=last_page_after,
        semantic_info=semantic_info,
    )
    return session


def _emit_terminal(
    task: SearchTask,
    session: OrganizeSession,
    rows: List[Dict[str, Any]],
    total: int,
    *,
    is_full: bool,
    semantic_info: Optional[str] = None,
) -> None:
    """终态发射半段：searchResults 回执 + 卡片 + agent_note + handle 尾行（不碰磁盘）。

    回执计数口径（D26）：fileCount=接口 totalCount 原样透传；dedupCount=去重后
    实际行数，仅 is_full 时输出（部分快照/截断省略该键）。

    ``semantic_info``：语义搜图（SemanticImage）首页返回的语义理解串，透传
    emit_card 注入卡片首行 ``searchParam.searchImageParam.semanticInfo``，供前端
    「加载更多」翻页原样回传后端首页语义理解结果；非语义模式为 None，emit_card
    经 ``attach_semantic_info_to_search_param`` 原样不注入。
    """
    emit_search_results(
        search_kind=task.search_kind,
        query=task.receipt_query,
        keyword=task.receipt_keyword,
        file_count=int(total or 0),
        dedup_count=len(rows) if is_full else None,
        keyword_hint=task.keyword_hint,  # D22 纯名词形态非阻断提示（仅语义模式可能置位）
    )
    # 卡片：total 原样取自接口 totalCount，禁止改写（前端会拿 searchParam 再取数）
    # audio-dynamic/video-dynamic：仅对卡片展示前 10 条富化 duration/contentSchedule（见
    # audio_video_dynamic_design.md）；落盘的 search.jsonl 不带富化字段（展示用，非搜索语义）
    media_meta = None
    if task.search_kind in ('audio-dynamic', 'video-dynamic') and rows:
        # best-effort：富化失败/超预算一律降级为 None（卡片照常出，无 duration/contentSchedule），
        # 永不阻断已成功的搜索终态（enrich_media_rows 内部亦有兜底，此为第二层防御）
        try:
            from services.search.media_enrich import enrich_media_rows
            media_meta = enrich_media_rows(rows[:10], task.content_type)
        except Exception:  # noqa: BLE001
            media_meta = None
    emit_card(
        search_kind=task.search_kind,
        rows=rows,
        total=int(total),
        search_param=search_param_payload(task),
        media_meta=media_meta,
        semantic_info=semantic_info,
    )
    emit_agent_note()
    # handle 尾行收尾（协议行放 stdout 最后才不被头部截断；与 refine/organize 同载体）
    emit_handle(Handle(id=f'{session.id}/search.jsonl'))


def _finalize(
    task: SearchTask,
    rows_unique: List[Dict[str, Any]],
    total: int,
    *,
    is_full: bool = True,
    semantic_info: Optional[str] = None,
    last_page_after: Any = None,
) -> None:
    """终态：落盘（原子写）+ 交接回执 + 卡片 + agent_note + handle 尾行。

    = ``_open_and_save`` + ``_emit_terminal`` 组合，view 与「full 单页即全量」共用。

    ``is_full``：本次落盘是否已含全量（本页游标空=true，下游 fetch_full 检测1
    命中短路零网络直导；部分快照=false，下游会续拉补全）。

    命中 0（无行且 total=0）：不产 handle——不建 op_xxx 会话目录、不落盘空文件
    （下游无物可引用，空 handle 目录纯属垃圾），回执省略 dedupCount 键、
    fileCount=0 并附 sayToUser 无结果建议 + tips 如实汇报约束（文案见 config），
    emit_card 同条件跳过卡片，agent_note 因无卡片登记自动省略。
    """
    if not rows_unique and not int(total):
        emit_search_results(
            search_kind=task.search_kind,
            query=task.receipt_query,
            keyword=task.receipt_keyword,
            file_count=0,
            keyword_hint=task.keyword_hint,  # D22 纯名词形态非阻断提示（仅语义模式可能置位）
        )
        return
    session = _open_and_save(
        task, rows_unique, total,
        is_full=is_full, last_page_after=last_page_after, semantic_info=semantic_info,
    )
    _emit_terminal(
        task, session, rows_unique, total, is_full=is_full, semantic_info=semantic_info,
    )


def _find_resumable_session(task: SearchTask) -> Optional[OrganizeSession]:
    """按参数指纹扫 plan_log 找可续拉会话（full 让出重跑的恢复入口）。

    合成 header（searchKind + 本任务参数快照）算指纹，与断点 meta 首行同口径
    （fetch_fingerprint 双侧剔 semanticInfo）。候选 = ``op_*`` 目录中
    fetch_progress.jsonl 首行 fetchMeta 指纹命中、且该目录 search.jsonl 仍存在
    （防手删结果文件后命中、runner 读侧报文件不存在）；多候选取断点 mtime 最新。
    单目录读异常跳过；扫描整体异常按未命中处理（宁可重拉不可错）。
    """
    try:
        header = {'searchKind': task.search_kind, task.param_key: task.param_payload}
        fingerprint = fetch_fingerprint(
            header, _KIND_TO_PAGE_SIZE.get(task.search_kind) or task.page_size,
        )
        best_name = ''
        best_mtime = 0.0
        for directory in plan_log_dir().glob('op_*'):
            if not HANDLE_RE.fullmatch(directory.name):
                continue
            try:
                progress = directory / CHECKPOINT_FILENAME
                meta = json.loads(
                    progress.read_text(encoding='utf-8').splitlines()[0].strip()
                )
                if (not isinstance(meta, dict)
                        or str(meta.get('record') or '') != 'fetchMeta'
                        or str(meta.get('fingerprint') or '') != fingerprint):
                    continue
                if not (directory / 'search.jsonl').is_file():
                    continue
                mtime = progress.stat().st_mtime
            except (OSError, IndexError, json.JSONDecodeError):
                continue
            if mtime > best_mtime:
                best_name, best_mtime = directory.name, mtime
        return OrganizeSession.open(best_name) if best_name else None
    except Exception:  # noqa: BLE001 扫描安全网：整体异常按未命中（宁可重拉不可错）
        return None


def run_view(task: SearchTask, *, on_first_response=None) -> None:
    """view 模式：单次请求（页大小=场景常量）即终态——不翻页、不续传，落盘到 handle。

    产 handle（``op_xxx/search.jsonl``）。``isFull`` 按本页游标判定（与 full 模式
    终态同口径）：没有下一页（``pageAfter`` 空）= 本页即全量 → ``isFull=true``，
    下游 plan 零网络直导；有下一页（``pageAfter`` 非空）= 部分快照 →
    ``isFull=false``，下游 ``ensure_full_results``（services.search_fetch）见此
    就地续拉补齐到全量。total 取接口 totalCount（单页响应亦有 total_count，
    needTotalCount=1 恒传），原样不改写。

    回执带 handle（供 agent 传下游 plan --from）+ 卡片 + agent_note。
    """
    fp = _fetch_first_page(task, on_first_response=on_first_response)
    # 「计数有、数据空」奇态拦截（2026-08-28 会话实证：takenAt 过滤下服务端
    # 计数与取数口径不一致，totalCount=727 但首页 fileList=[]）。此时落盘必然是
    # 0 行部分快照，下游 plan 读侧报「无有效文件记录」且重试无法自愈——直接
    # error 回执，行动指引指向 --mode full（全量口径不同，能拿到真实数据）。
    # 真·命中 0（totalCount=0）不在此列，仍走正常 ok 终态。
    if not fp.rows and fp.total > 0:
        raise SearchServiceError(
            f'服务端返回异常：命中计数为 {fp.total} 但本次未取到任何数据'
            f'（接口计数与取数口径不一致）；请改用 --mode full 重新搜索'
        )
    _finalize(
        task, fp.rows, fp.total,
        is_full=fp.next_after is None,
        semantic_info=fp.semantic_info, last_page_after=fp.next_after,
    )


def run_search(task: SearchTask, *, on_first_response=None) -> None:
    """执行一次搜索：view=单页快速返回；full=首页落盘 + ensure_full 就地续拉。

    结果落盘到 ``<plan_log>/<会话id>/search.jsonl``（回执 handle 即此相对路径），经 stdout 回执交接（无返回值；
    main 调用方按 record=searchResults 行解析 handle）。
    ``on_first_response``：首页响应钩子（业务成功判定后调用；person-search 的
    merge/image 首页歧义守卫用，可抛控制流异常终止；None=无操作，既有调用方
    零感知；full 续跑命中断点时不触发——从断点游标续拉，无首页响应）。
    """
    if task.mode == 'view':
        run_view(task, on_first_response=on_first_response)
        return
    _run_full(task, on_first_response=on_first_response)


def _run_full(task: SearchTask, *, on_first_response=None) -> None:
    """full 模式：首页取数落盘 → ensure_full_results 就地续拉 → 终态发射。

    断点 = ``op_xxx/fetch_progress.jsonl``（与 refine/organize 同机制，由
    services.search_fetch 的 runner 维护）；让出（FetchYield）原样上抛——cli 层
    转 yielded 回执，重跑同一命令经 ``_find_resumable_session`` 指纹命中即续拉。
    """
    session = _find_resumable_session(task)
    if session is None:
        fp = _fetch_first_page(task, on_first_response=on_first_response)
        if (not fp.rows and not fp.total) or fp.next_after is None:
            # 命中 0（仅 0 回执，不建会话不落盘）或单页即全量（isFull=true 直接
            # 终态，无需续拉）——都与 view 同路走 _finalize
            _finalize(
                task, fp.rows, fp.total, is_full=True,
                semantic_info=fp.semantic_info, last_page_after=None,
            )
            return
        # 部分快照落盘（isFull=false + header 带首页游标），交给 ensure_full_results
        # 续拉（runner 检测1短路不适用、检测见 header lastPageAfter 种入断点续拉）
        session = _open_and_save(
            task, fp.rows, fp.total,
            is_full=False, last_page_after=fp.next_after,
            semantic_info=fp.semantic_info,
        )
    try:
        files, header, _pulled = ensure_full_results(session.search_path)
    except FetchYield:
        raise  # 让出 ≠ 失败：断点已落盘，原样重跑同一命令即从断点续拉
    except (ValueError, RuntimeError) as exc:
        raise SearchServiceError(f'全量拉取失败：{exc}；请停止并交用户决策') from exc
    _emit_terminal(
        task, session,
        [f.model_dump(by_alias=True, mode='json') for f in files],
        int(header.get('totalCount') or 0),
        is_full=bool(header.get('isFull')),
        # semanticInfo 从回写后 header 的参数快照取（save_results 已注入，续拉
        # 整区灌回请求后仍在）——仅语义搜图有此键
        semantic_info=(
            (header.get('searchImageParam') or {}).get('semanticInfo')
            if task.param_key == 'searchImageParam' else None
        ),
    )


__all__ = ['run_search']
