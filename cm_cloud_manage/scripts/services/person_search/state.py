#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""歧义态落盘/读回：``op_xxxxxx/ambiguity.jsonl``（queryA + recognizeQuery + fileIds 快照）。

单行 JSONL，``record=ambiguityHeader``（与 search 的 ``searchResultsArgs``/``searchHeader``/
``file`` 区分——误读也不被 search 读侧 ``_HEADER_RECORDS`` 认作 header/file）。歧义轮
落盘出 handle，选脸二次搜索带 ``--from op_xxxxxx/ambiguity.jsonl`` 由
``read_ambiguity_state`` 读回：queryA 供展示口径 ``queryA#queryB`` 拼接；recognizeQuery
（首轮发 face/recognize 的 wire text 原串）供二次轮请求 text ``recognizeQuery#queryB``
拼接。旧格式快照（无 recognizeQuery 键）不兼容：读回报 USAGE，要求重新首搜。

复用 ``OrganizeSession`` 全套（create/open/_atomic_write_text），公共库零改动。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Tuple

from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)

from services.errors import CliValidationError

_RECORD = 'ambiguityHeader'


def write_ambiguity_state(
    session: OrganizeSession, *, query: str, recognize_query: str,
    file_ids: List[str],
) -> str:
    """原子写 ``ambiguity.jsonl``（单行），返回 handle ``op_xxxxxx/ambiguity.jsonl``。

    ``recognize_query``：首轮发 face/recognize 的 wire text 原串
    （``{"user_query", "bindings"}`` JSON），二次轮请求 text 拼接用。
    """
    row = {
        'record': _RECORD,
        'query': query,
        'recognizeQuery': recognize_query,
        'fileIds': list(file_ids),
        'createdAt': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    }
    OrganizeSession._atomic_write_text(
        session.dir / 'ambiguity.jsonl',
        json.dumps(row, ensure_ascii=False) + '\n',
    )
    return f'{session.id}/ambiguity.jsonl'


def read_ambiguity_state(handle: str) -> Tuple[str, str, List[str]]:
    """读 ``ambiguity.jsonl`` → ``(queryA, recognizeQuery, fileIds)``；坏抛 ``CliValidationError``。

    ``recognizeQuery`` 缺失/空（旧格式快照）不拒识：返回空串，由 flow 端回退
    歧义快照的 ``query`` 作二次请求前段（2026-09-14 定案）。``handle`` 容忍裸
    ``op_xxxxxx`` 或 ``op_xxxxxx/ambiguity.jsonl``（``OrganizeSession.open``
    自动剥离文件段，只取会话 id）。
    """
    try:
        session = OrganizeSession.open(handle)
    except OrganizeSessionError as exc:
        raise CliValidationError(
            f'person-search：--from 会话不存在或格式不对：{exc}'
        ) from exc
    path = session.dir / 'ambiguity.jsonl'
    if not path.is_file():
        raise CliValidationError(
            f'person-search：会话 {session.id} 下没有 ambiguity.jsonl'
            '（无可承接的需要澄清状态）'
        )
    try:
        first = path.read_text(encoding='utf-8').splitlines()[0]
        row = json.loads(first)
    except (json.JSONDecodeError, OSError, IndexError) as exc:
        raise CliValidationError(
            f'person-search：ambiguity.jsonl 损坏：{exc}'
        ) from exc
    if not isinstance(row, dict) or row.get('record') != _RECORD:
        raise CliValidationError(
            f'person-search：ambiguity.jsonl 首行 record 不是 {_RECORD}'
        )
    query = row.get('query')
    if not isinstance(query, str) or not query.strip():
        raise CliValidationError(
            'person-search：ambiguity.jsonl 缺少 query 字段或为空'
        )
    recognize_query = row.get('recognizeQuery')
    if not isinstance(recognize_query, str) or not recognize_query.strip():
        # 旧格式快照（无 recognizeQuery）：不再拒识——返回空串，flow 端回退 query
        recognize_query = ''
    file_ids = row.get('fileIds') or []
    if not isinstance(file_ids, list):
        raise CliValidationError(
            'person-search：ambiguity.jsonl fileIds 字段格式错'
        )
    return query, recognize_query, [str(x) for x in file_ids]


__all__ = ['write_ambiguity_state', 'read_ambiguity_state']
