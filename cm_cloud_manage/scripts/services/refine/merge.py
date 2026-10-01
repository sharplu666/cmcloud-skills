#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge 编排：合并多个数据 jsonl 产新语料 ``merged.jsonl``。

管道：逐输入开 session → 铁律检查（search 输入 ``isFull≠true`` 就地续拉回写，
让出 FetchYield 原样上抛；dedup/select/merged 终态产物 ``isFull≠true`` 报错要求
重建，绝不进续拉）→ 新会话 ``OrganizeSession.create()`` 流式合并落盘（行透传 +
seen-fileId 集保首现，防 k×大结果集全量驻内存）→ meta 记产物 → 回执 + 单张预览卡。

merge 是「并」不是「选」（docs/cli_design.md §9）：产物是**新语料**而非子集——
header 复用第一输入的搜索核心字段 + ``resultRole=merged`` + ``mergeSources`` 汇总，
无 ``refineKind``；行无 ``bucket`` 键，原标签与来源降级 ``srcBucket``/``srcFile``
逐行存档（仅溯源；``File.model_validate`` 的 ``extra='ignore'`` 会静默忽略）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Tuple

from cli_timing import write_cli_output_line
from mclaw.api.search_fusion import File
from mclaw.shared.cm_cloud.card_meta import build_search_result_summary
from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)
from mclaw.shared.organize.preview_cards import (
    BUCKET_CARD_ROW_LIMIT,
    file_to_preview_row,
    render_static_card,
)
from mclaw.shared.organize.tools.search_results_io import SearchResultsHeader

from services.errors import OperationServiceError, ensure_full_search_results
from services.refine.subset_io import is_merged_header, read_subset_header
from services.stdout_receipt import Handle, emit_handle, ok_meta

if TYPE_CHECKING:
    from cli.refine import MergeTask  # noqa: F401 仅供类型注解（运行期零依赖）

__all__ = ['run_merge']

#: nextSteps 命令模板用的 main.py 绝对路径（services/refine/merge.py 的 parents[2] 即 scripts 目录）
_MAIN_PY = str(Path(__file__).resolve().parents[2] / 'main.py')

#: 终态产物文件名 → header 判别方式（坏文件兜底：文件名合法但 header 标记不符）
_TERMINAL_KINDS = {'dedup.jsonl': 'dedup', 'select.jsonl': 'select'}


def run_merge(task: 'MergeTask') -> None:
    """合并 ``task.inputs`` → 新会话 ``op_<new>/merged.jsonl``（见模块 docstring）。"""
    # 1) 逐输入检查（先全部检查完再动笔：续拉让出时不产任何半成品；重复条目静默去重）
    prepared: List[Tuple[str, str, Path, Dict]] = []
    seen_entries = set()
    for handle, filename in task.inputs:
        if (handle, filename) in seen_entries:
            continue
        seen_entries.add((handle, filename))
        try:
            session = OrganizeSession.open(handle)
        except OrganizeSessionError as exc:
            raise OperationServiceError(str(exc)) from exc
        path = session.dir / filename
        if not path.is_file():
            raise OperationServiceError(
                f'会话 {session.id} 没有 {filename}；'
                f'请确认 {handle}/{filename} 存在（由搜索或 refine/merge 产出）。'
            )
        header = read_subset_header(path)
        if filename == 'search.jsonl':
            # 铁律：search 部分快照就地续拉补全回写（让出 ≠ 失败，原样重跑续拉）
            if not bool(header.get('isFull')):
                header = ensure_full_search_results(str(path))
        else:
            if not _terminal_header_ok(filename, header):
                raise OperationServiceError(
                    f'{handle}/{filename} 不是合法的 {filename[:-6]} 产物'
                    '（header 标记不符）；请重新生成后再合并。'
                )
            if not bool(header.get('isFull')):
                raise OperationServiceError(
                    f'{handle}/{filename} 的 isFull≠true，属于异常产物；'
                    '请从原始输入重新生成或重新 merge 重建，不要直接续拉。'
                )
        prepared.append((handle, filename, path, header))

    # 2) 新会话 + 流式合并（行透传 + fileId 保首现；输入序即行序）
    session = OrganizeSession.create()
    rows_tmp = session.dir / '.merged.rows.tmp'
    seen_ids = set()
    sources: List[Dict[str, object]] = []
    total_in = 0
    count = 0
    try:
        with rows_tmp.open('w', encoding='utf-8') as out:
            for handle, filename, path, _header in prepared:
                kept = 0
                with path.open(encoding='utf-8') as fp:
                    for raw in fp:
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OperationServiceError(
                                f'{handle}/{filename} 含非法 JSON 行: {exc}'
                            ) from exc
                        if row.get('record') != 'file':
                            continue
                        total_in += 1
                        # 标签降级存档：pop 活动 bucket → srcBucket；注入 srcFile 溯源
                        src_bucket = str(row.pop('bucket', '') or '')
                        fid = str(row.get('fileId') or '')
                        if fid:
                            if fid in seen_ids:
                                continue
                            seen_ids.add(fid)
                        row['srcFile'] = f'{handle}/{filename}'
                        row['srcBucket'] = src_bucket
                        out.write(json.dumps(row, ensure_ascii=False) + '\n')
                        kept += 1
                        count += 1
                sources.append(
                    {'handle': handle, 'file': filename, 'count': kept}
                )
        if count == 0:
            raise OperationServiceError(
                '合并后无有效文件记录；请检查输入文件内容'
            )

        # 3) header（第一输入的搜索核心字段 + 语料标记）+ 原子落盘
        header_model = SearchResultsHeader.model_validate(prepared[0][3])
        header_row = header_model.to_row()
        header_row.pop('lastPageAfter', None)  # merged 是终态语料，无翻页游标（协议）
        header_row['record'] = 'searchHeader'
        header_row['isFull'] = True
        header_row['totalCount'] = count
        header_row['resultRole'] = 'merged'
        header_row['mergeSources'] = sources
        final_tmp = session.dir / '.merged.jsonl.tmp'
        with final_tmp.open('w', encoding='utf-8') as out:
            out.write(json.dumps(header_row, ensure_ascii=False) + '\n')
            with rows_tmp.open(encoding='utf-8') as fp:
                for raw in fp:
                    out.write(raw if raw.endswith('\n') else raw + '\n')
        os.replace(final_tmp, session.dir / 'merged.jsonl')
    finally:
        if rows_tmp.exists():
            rows_tmp.unlink()

    # 4) meta 记产物
    session.merge_meta({
        'merge_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'merge_file': 'merged.jsonl',
        'merge_count': count,
        'merge_sources': sources,
    })

    # 5) 回执：data 只留 outputFile（下游 plan --from 消费）与 fileCount（规则 11）
    rel = f'{session.id}/merged.jsonl'
    ok_meta(
        'refine',
        say_to_user=f'{total_in} 个文件合并后保留 {count} 个。',
        next_steps={'plan': (
            f'python3 {_MAIN_PY} organize --step plan '
            f'--from {rel} [--bucket …] / [--parent-path <名>]'
        )},
        data={'outputFile': rel, 'fileCount': count},
    )
    # 6) 结果预览卡：单卡前 10 行（与 dedup 同款，恒截断；全量明细在 merged.jsonl）
    _emit_card(session.dir / 'merged.jsonl', count)
    # 7) handle 行收尾（协议行放 stdout 尾部，防 openclaw exec 头部截断）
    emit_handle(Handle(id=rel, params={'kind': 'merge'}))


def _terminal_header_ok(filename: str, header: Dict) -> bool:
    """终态产物 header 标记判别：merged 看 resultRole；dedup/select 看 refineKind。"""
    if filename == 'merged.jsonl':
        return is_merged_header(header)
    expected = _TERMINAL_KINDS.get(filename)
    return bool(expected) and str(header.get('refineKind') or '') == expected


def _emit_card(merged_path: Path, count: int) -> None:
    previews: List[File] = []
    with merged_path.open(encoding='utf-8') as fp:
        for raw in fp:
            if len(previews) >= BUCKET_CARD_ROW_LIMIT:
                break
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get('record') != 'file':
                continue
            row.pop('srcFile', None)
            row.pop('srcBucket', None)
            previews.append(File.model_validate(row))
    rows = [
        file_to_preview_row(f, index=idx, file_type='image')
        for idx, f in enumerate(previews, start=1)
    ]
    summary = build_search_result_summary(
        file_type='image', total=count, shown=len(rows),
    )
    for line in render_static_card(
        file_type='image', rows=rows, summary=summary
    ).splitlines():
        write_cli_output_line(line)
