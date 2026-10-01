#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-by-ids 终态：search_by_fileId 全量取数 → 落盘 search.jsonl → 回执。

与 fetch_loop 的差异（按 search-by-ids 业务规则）：
  - 同步接口一次取全量：无翻页、无 --mode、无断点续传；``isFull`` 恒 true。
  - **不发任何卡片**（无 :::fileList 围栏块），终态仅 record=searchResults
    回执 + handle 尾行。
  - header ``searchKind='searchByFileIds'``；接口请求快照以扩展键
    ``searchByFileIdsParam``（{fileIds:[...]}）落进 header（读侧
    ``SearchResultsHeader extra='ignore'`` 天然容忍，与 person 扩展键同手法）。
  - 接口请求 fileId 数 ≠ 返回行数时，回执 ``tips`` 前置缺失提示（API 层
    ``_build_result`` 已双写丢失 fileId 日志，回执只带计数口径）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mclaw.api.search_fusion import File
from mclaw.api.search_fusion.search_by_fileId import SearchByFileIdRequest
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.organize.organize_session import OrganizeSession, OrganizeSessionError
from mclaw.shared.organize.tools.search_results_io import SearchResultsHeader

from services.errors import OperationServiceError
from services.search.errors import SearchServiceError
from services.search.stdout_receipt import emit_search_results
from services.stdout_receipt import Handle, emit_handle

#: header 的 searchKind 字面量（用户定案；runner _KIND_TO_PAGE_SIZE 已登记同名兜底）
SEARCH_KIND = 'searchByFileIds'


def _save_search_jsonl(
    files: List[File],
    file_ids: List[str],
    output_path: Path,
) -> None:
    """header + file 行原子落盘（与 save_search_results 同构，扩展键带请求快照）。"""
    base = SearchResultsHeader(
        search_kind=SEARCH_KIND,
        query='',
        file_type='file',
        page_size=len(files),
        deduplicate_similar=False,
        total_count=len(files),
        is_full=True,
    ).to_row()
    base['searchByFileIdsParam'] = {'fileIds': list(file_ids)}
    lines = [json.dumps(base, ensure_ascii=False)]
    lines.extend(
        json.dumps(
            {'record': 'file', **f.model_dump(by_alias=True, mode='json')},
            ensure_ascii=False,
        )
        for f in files
    )
    tmp_path = output_path.with_name(f'{output_path.name}.tmp{os.getpid()}')
    tmp_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.replace(tmp_path, output_path)


def run_search_by_ids_search(
    file_ids: List[str],
    *,
    dispatcher: Optional[Any] = None,
) -> None:
    """全量取数 → 落盘 → 回执（无返回值；结果经 stdout 交接）。

    接口对存在 id 返回 0 行（``files`` 为空）：不建会话、不落盘，仅发
    ``fileCount=0`` 回执（无 handle 尾行）。
    """
    dispatcher = dispatcher or get_cloud_dispatcher()
    resp = dispatcher.search_fusion.search_by_fileId(
        SearchByFileIdRequest(file_list=list(file_ids))
    )
    if not getattr(resp, 'success', False) or str(getattr(resp, 'code', '')) != '0000':
        server_msg = str(getattr(resp, 'message', '') or '').strip() or '查询失败'
        trace_id = str(getattr(resp, 'trace_id', '') or '').strip()
        trace_part = f'（traceId={trace_id}）' if trace_id else ''
        raise OperationServiceError(
            f'查询文件AI信息失败：{server_msg}{trace_part}；请停止并交用户决策，勿自动重试'
        )

    files: List[File] = list(resp.file_list or [])
    if not files:
        emit_search_results(search_kind=SEARCH_KIND, file_count=0)
        return

    try:
        session = OrganizeSession.create()
    except OrganizeSessionError as exc:
        raise SearchServiceError(f'建立搜索会话失败：{exc}；请停止并交用户决策') from exc
    try:
        _save_search_jsonl(files, file_ids, session.search_path)
    except Exception as exc:
        raise SearchServiceError(
            f'内部错误：结果落盘失败（{type(exc).__name__}: {exc}）；请停止并交用户决策'
        ) from exc

    # 输入/输出条数不一致 → tips 前置缺失提示（丢失明细已由 API 层双写日志）
    tips_prefix = ''
    if len(files) != len(file_ids):
        tips_prefix = f'部分 fileId 未返回结果：实际返回{len(files)}个；'
    emit_search_results(
        search_kind=SEARCH_KIND,
        file_count=len(files),
        dedup_count=len(files),
        tips_prefix=tips_prefix,
    )
    emit_handle(Handle(id=f'{session.id}/search.jsonl'))


__all__ = ['run_search_by_ids_search', 'SEARCH_KIND']
