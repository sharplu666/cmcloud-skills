#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-transfer 编排：单次 legacy 查询 → 业务码校验 → 富化发卡（不落盘）。

纯查询：不建会话、不写 jsonl、不产 handle、无让出。回执 Meta 管理（对齐
refine/organize 首行 Meta 惯例）：meta 恒第 1 行（sayToUser 用户向计数、
data.fileCount=接口 total 透传、有下一页 next.next-page=完整翻页命令——全部
参数显式固化，仅追加 --page-after），随后卡片收尾。
"""

from __future__ import annotations

from pathlib import Path

from mclaw.api.personal_saas.query_personal_dynamic_api import (
    QueryPersonalDynamicRequest,
)
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from services.search.errors import SearchServiceError
from services.search_transfer.args import SearchTransferArgs
from services.search_transfer.cards import build_transfer_card_rows, emit_transfer_card
from services.stdout_receipt import ok_meta
from utils.config import SEARCH_TRANSFER_ZERO_RESULTS

__all__ = ['run_search_transfer']

#: 翻页命令模板用的 main.py 绝对路径
_MAIN_PY = str(Path(__file__).resolve().parents[2] / 'main.py')


def _q(value: str) -> str:
    """翻页命令里的参数引号包裹（单引号 + POSIX 转义 `'` → `'\\''`）。

    回执中的命令会被 agent 原样执行，keyword（用户输入）与游标（服务端数据）
    内嵌单引号都会打断引号即注入；转义后 shlex 仍正确还原原值。
    """
    escaped = str(value).replace("'", "'\\''")
    return f"'{escaped}'"


def _next_page_cmd(targs: SearchTransferArgs, cursor: str) -> str:
    """完整翻页命令：全部参数显式固化（含缺省固化的 end-at），仅追加游标。"""
    return (
        f'python3 {_MAIN_PY} search-transfer'
        f' --start-at {_q(targs.start_at)} --end-at {_q(targs.end_at)}'
        f' --keyword {_q(targs.keyword)} --transfer-type {targs.transfer_type}'
        f' --page-size {targs.page_size} --page-after {_q(cursor)}'
    )


def run_search_transfer(targs: SearchTransferArgs) -> None:
    """转存查询单页执行：查询 → 校验 → 富化 → meta + dynamicList 卡。"""
    dispatcher = get_cloud_dispatcher()
    resp = dispatcher.personal_saas.query_personal_dynamic(
        QueryPersonalDynamicRequest(
            start_time=targs.start_at,
            end_time=targs.end_at,
            keyword=targs.keyword,
            page_size=targs.page_size,
            dynamic_type=targs.transfer_type,
            next_page_cursor=targs.page_after,
        )
    )
    if not resp.success:
        raise SearchServiceError(
            f'转存查询失败 [{resp.code}]：{resp.message or "服务端返回异常"}'
        )
    rows = resp.skill_file_list
    if not rows and not resp.next_page_cursor:
        ok_meta(
            'search-transfer',
            say_to_user=SEARCH_TRANSFER_ZERO_RESULTS,
            data={'fileCount': resp.total},
        )
        return
    if not rows:
        # 空页带游标（页边界奇态）：翻页链不能断，如实报「本页 0 条」并给翻页命令
        ok_meta(
            'search-transfer',
            say_to_user=f'共 {resp.total} 条转存记录，本页 0 条。',
            next_steps={'next-page': _next_page_cmd(targs, resp.next_page_cursor)},
            data={'fileCount': resp.total},
        )
        return

    card_rows = build_transfer_card_rows(rows, dispatcher)
    next_steps = {}
    if resp.next_page_cursor:
        next_steps['next-page'] = _next_page_cmd(targs, resp.next_page_cursor)
    ok_meta(
        'search-transfer',
        say_to_user=f'共 {resp.total} 条转存记录，本页 {len(rows)} 条。',
        next_steps=next_steps,
        data={'fileCount': resp.total},
    )
    emit_transfer_card(card_rows)
