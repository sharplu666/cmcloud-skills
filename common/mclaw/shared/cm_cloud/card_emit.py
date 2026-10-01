#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一输出 ``:::卡片名`` 围栏块（末行 ``meta`` 走 ``card_meta`` 配置）。

内部委托 ``Card.generate()`` 组装各行（单一组装路径），cardId 仍由
``preview_cards.card_result_meta_line`` 经 ``Card`` 注入。保留 ``write_line`` 回调
签名向后兼容。
"""

from __future__ import annotations

import warnings
from typing import Any, Callable, Dict, List, Optional

WriteLine = Callable[[str], None]


def _warn_missing_cli(cli: str, card: str) -> None:
    if str(cli or '').strip():
        return
    warnings.warn(
        f'emit_card_block({card!r}): cli 为空，meta 将回退为 resultType=search 且无 summary；'
        f'请传入 CLI 子命令名（见 mclaw.shared.cm_cloud.card_meta.CARD_META_BY_CLI）',
        UserWarning,
        stacklevel=3,
    )


def emit_card_block(
    card_name: str,
    header: Optional[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    *,
    write_line: WriteLine,
    cli: str = '',
    count: Optional[int] = None,
    result_type: Optional[str] = None,
    summary: Optional[str] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> None:
    """输出 :::卡片名 块；末行 meta 走 ``card_meta``。

    内部经 ``Card(...).generate()`` 组装（含 ``<frontend_card>`` 包裹 + 末行 meta +
    cardId 注入），逐行经 ``write_line`` 回调写出。``result_type`` / ``summary`` 非
    None 时覆盖 ``card_meta`` 配置。
    """
    from mclaw.shared.cm_cloud.card import Card

    _warn_missing_cli(cli, card_name)
    for line in Card(
        card_name,
        rows,
        header=header,
        cli=cli,
        count=count,
        result_type=result_type,
        summary=summary,
        extra_meta=extra_meta,
    ).generate():
        write_line(line)


__all__ = ['WriteLine', 'emit_card_block']
