#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 卡片便捷封装：默认走 ``write_cli_output_line``，无需再经 manage utils。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from mclaw.shared.cm_cloud.card_emit import emit_card_block as _emit_card_block

_KB_REFERENCE_RESOURCE_KEYS = (
    'resourceId',
    'resourceType',
    'baseId',
    'name',
    'highlightName',
    'type',
    'category',
    'size',
    'fileExtension',
)


def _without_highlight_spans(value: str) -> str:
    """仅移除接口约定的高亮标签，保留其余文本用于严格比较。"""
    return value.replace('<span>', '').replace('</span>', '')


def knowledge_base_file_row(
    item: Mapping[str, Any],
    *,
    base_id: str = '',
    base_name: str = '',
) -> Dict[str, str]:
    """知识库文件列表行：仅 resourceId / name / baseName / baseId。"""
    res = item.get('resource') if isinstance(item.get('resource'), dict) else item
    return {
        'resourceId': str(res.get('resourceId') or item.get('resourceId') or '').strip(),
        'name': str(
            res.get('name') or res.get('folderName') or item.get('name') or ''
        ).strip(),
        'baseName': str(
            res.get('baseName') or item.get('baseName') or base_name or ''
        ).strip(),
        'baseId': str(res.get('baseId') or item.get('baseId') or base_id or '').strip(),
    }


def knowledge_base_reference_row(item: Mapping[str, Any]) -> Dict[str, Any]:
    """知识分片检索行：按内容关系选择原文分片和高亮分片字段。"""
    raw = dict(item) if isinstance(item, dict) else {'resource': item}
    resource = raw.get('resource') if isinstance(raw.get('resource'), dict) else {}
    trimmed: Dict[str, Any] = {}
    for key in _KB_REFERENCE_RESOURCE_KEYS:
        if key not in resource:
            continue
        value = resource[key]
        if value is None:
            continue
        if key in {'name', 'highlightName'} and not str(value).strip():
            continue
        trimmed[key] = value
    sharding = raw.get('shardingList')
    if not isinstance(sharding, list):
        sharding = []
    sharding = [str(x) for x in sharding]
    highlight_sharding = raw.get('highlightShardingList')
    if not isinstance(highlight_sharding, list):
        highlight_sharding = []
    highlight_sharding = [str(x) for x in highlight_sharding]
    row: Dict[str, Any] = {
        'resource': trimmed,
        'baseName': str(raw.get('baseName') or '').strip(),
    }

    if highlight_sharding:
        normalized_highlight = [_without_highlight_spans(x) for x in highlight_sharding]
        if sharding and normalized_highlight != sharding:
            row['shardingList'] = sharding
        row['highlightShardingList'] = highlight_sharding
    elif sharding:
        row['shardingList'] = sharding
    return row


def _write_line(line: str) -> None:
    from cli_timing import write_cli_output_line

    write_cli_output_line(line)


def emit_card_block(
    card_name: str,
    header: Optional[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    *,
    cli: str = '',
    count: Optional[int] = None,
    result_type: Optional[str] = None,
    summary: Optional[str] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> None:
    """输出 :::卡片名 块；末行 meta 走 ``card_meta``。"""
    _emit_card_block(
        card_name,
        header,
        rows,
        write_line=_write_line,
        cli=cli,
        count=count,
        result_type=result_type,
        summary=summary,
        extra_meta=extra_meta,
    )


def emit_file_path_list_card(
    rows: List[Dict[str, Any]],
    *,
    cli: str = '',
    summary: Optional[str] = None,
    shown_by_button: Optional[bool] = None,
) -> None:
    """输出 :::filePathList（无 loadMore 首行；末行 meta）。"""
    if not rows:
        return
    count = len(rows)
    if shown_by_button is None:
        shown_by_button = count > 5
    emit_card_block(
        'filePathList',
        None,
        rows,
        cli=cli,
        count=count,
        summary=summary,
        extra_meta={'shownByButton': bool(shown_by_button)},
    )


def emit_knowledge_base_file_card(
    rows: List[Dict[str, Any]],
    *,
    cli: str = '',
    count: Optional[int] = None,
    header: Optional[Dict[str, Any]] = None,
) -> None:
    """输出 :::knowledgeBaseFile（首行为查看更多行）。"""
    if not rows and not header:
        return
    emit_card_block(
        'knowledgeBaseFile',
        header,
        rows,
        cli=cli,
        count=len(rows) if count is None else int(count),
    )


def emit_knowledge_base_reference_card(
    rows: List[Dict[str, Any]],
    *,
    cli: str = '',
) -> None:
    """输出 :::knowledgeBaseReference（仅分片检索；无 loadMore 首行）。"""
    trimmed = [knowledge_base_reference_row(row) for row in rows]
    trimmed = [
        row
        for row in trimmed
        if row.get('resource') or row.get('shardingList') or row.get('highlightShardingList')
    ]
    if not trimmed:
        return
    emit_card_block(
        'knowledgeBaseReference',
        None,
        trimmed,
        cli=cli,
        count=len(trimmed),
    )


def emit_knowledge_base_path_card(
    row: Dict[str, Any],
    *,
    cli: str = '',
) -> None:
    """输出 :::knowledgeBasePath（单行数据）。"""
    if not row.get('baseId'):
        return
    emit_card_block(
        'knowledgeBasePath',
        None,
        [row],
        cli=cli,
        count=1,
    )


def emit_contacts_card(
    rows: List[Dict[str, Any]],
    *,
    cli: str = 'share_friend',
) -> None:
    """输出 :::contacts（好友分享回执）。"""
    if not rows:
        return
    emit_card_block(
        'contacts',
        None,
        rows,
        cli=cli,
        count=len(rows),
    )


__all__ = [
    'emit_card_block',
    'emit_contacts_card',
    'emit_file_path_list_card',
    'emit_knowledge_base_file_card',
    'emit_knowledge_base_path_card',
    'emit_knowledge_base_reference_card',
    'knowledge_base_file_row',
    'knowledge_base_reference_row',
]
