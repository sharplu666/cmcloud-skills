#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 输出：JSONL、卡片、记录富化、格式化。"""
from __future__ import annotations

from cli_timing import (
    build_failapi_record,
    clear_api_timings,
    write_cli_output_line,
)
from cli_trace import get_primary_api_context
from utils.config import (
    CARD_FILE_LIST,
    CARD_IMAGE_LIST,
    LOAD_MORE_TOTAL_THRESHOLD,
    SEARCH_LIST_COMMANDS,
    SEARCH_TYPES_FILE_LIST_CONTROL,
    WORKSPACE_DIR,
)
from operation_log import init_operation_log as _init_operation_log
from typing import Any, Optional

from mclaw.shared.postprocess.cli_rows import (  # noqa: F401
    format_bytes,
    semantic_image_file_record,
)
from mclaw.shared.cm_cloud.card import Card  # noqa: E402
from mclaw.shared.cm_cloud.cli_cards import (  # noqa: E402
    emit_file_path_list_card as _emit_file_path_list_card_shared,
)
from mclaw.shared.cm_cloud.card_output import (
    attach_semantic_info_to_search_param,
    normalize_search_param_for_card_output,
)
from mclaw.shared.cm_cloud.cli_jsonl import emit_jsonl as _emit_jsonl  # noqa: E402


def init_operation_log(*, command: str) -> None:
    """登记写操作日志上下文（委托 common_auth.operation_log）。"""
    _init_operation_log(command=command, workspace_dir=WORKSPACE_DIR)


def emit_jsonl(payload: dict[str, Any]) -> None:
    _emit_jsonl(payload, write_line=write_cli_output_line)


def load_more_type(total: int) -> str:
    """总数大于 10 时返回 "true"，否则 "false"。"""
    try:
        return 'true' if int(total) > LOAD_MORE_TOTAL_THRESHOLD else 'false'
    except (TypeError, ValueError):
        return 'false'


def card_search_param(
    request_payload: Optional[dict] = None,
    semantic_info: Optional[str] = None,
) -> dict:
    """卡片首行 searchParam：完整的主接口请求参数（含分页）。

    ``semantic_info`` 非空时（语义搜图首页）把 ``semanticInfo`` 注入 searchParam
    （置于 pageInfo 之前，保 #71 字段序）；翻页不传 → 不注入。
    """
    if request_payload is None:
        _, request_payload = get_primary_api_context()
    payload = request_payload or {}
    sp = payload.get('searchParam')
    base = normalize_search_param_for_card_output(sp if isinstance(sp, dict) else payload)
    if semantic_info:
        return attach_semantic_info_to_search_param(base, semantic_info)
    return base


def build_card_header(
    *,
    total: int,
    search: bool = True,
    semantic_info: Optional[str] = None,
) -> dict[str, Any]:
    """卡片首行：loadMore / total / searchParam（写操作 search=False 时 searchParam 为 null）。"""
    return {
        'loadMore': load_more_type(total),
        'total': int(total),
        'searchParam': card_search_param(semantic_info=semantic_info) if search else None,
    }


def emit_file_list_card(
    rows: list[dict[str, Any]],
    *,
    total: Optional[int] = None,
    search: bool = False,
    include_header: bool = True,
    cli: str = '',
    summary: Optional[str] = None,
) -> None:
    """输出 :::fileList 块（可选 loadMore 首行；末行 meta 走 card_meta 配置）。"""
    total_n = len(rows) if total is None else int(total)
    header = build_card_header(total=total_n, search=search) if include_header else None
    for line in Card(
        CARD_FILE_LIST, rows, header=header, cli=cli, count=total_n, summary=summary
    ).generate():
        write_cli_output_line(line)


def emit_file_path_list_card(
    rows: list[dict[str, Any]],
    *,
    summary: Optional[str] = None,
    shown_by_button: Optional[bool] = None,
    cli: str = '',
) -> None:
    """输出 :::filePathList 块（无 loadMore 首行；末行 meta）。"""
    _emit_file_path_list_card_shared(
        rows,
        cli=cli,
        summary=summary,
        shown_by_button=shown_by_button,
    )


def emit_image_list_card(
    rows: list[dict[str, Any]],
    *,
    total: Optional[int] = None,
    search: bool = True,
    include_header: bool = True,
    semantic_info: Optional[str] = None,
    cli: str = '',
    summary: Optional[str] = None,
) -> None:
    total_n = len(rows) if total is None else int(total)
    header = (
        build_card_header(total=total_n, search=search, semantic_info=semantic_info)
        if include_header else None
    )
    for line in Card(
        CARD_IMAGE_LIST, rows, header=header, cli=cli, count=total_n, summary=summary
    ).generate():
        write_cli_output_line(line)


def command_uses_search_card_header(command: str) -> bool:
    """个人云搜索/列举命令的 fileList 卡片须带 searchParam 首行。"""
    if command not in SEARCH_LIST_COMMANDS:
        return False
    search_type, _ = get_primary_api_context()
    return search_type in SEARCH_TYPES_FILE_LIST_CONTROL
