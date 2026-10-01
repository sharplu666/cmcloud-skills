#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""person-search 歧义卡片：``:::selectFaceList`` + 歧义态落盘。

歧义终态三件事：(1) 落 ``op_xxxxxx/ambiguity.jsonl``（queryA + fileIds 快照）；
(2) 发 meta ok（``say_to_user`` = 接口 ``reasonText``+``selectText`` 原样 + 三选一
搜索范围确认指引固定追加，N 由模型理解文案后替换）+ ``:::selectFaceList`` 卡；
(3) handle 尾行 ``params.ambiguity=true``
标记需澄清（用户选脸后 ``--select-faces --from`` 承接，与成功终态 ``ambiguity=false``
二值区分，提示层据此判定、不自行推断）。

行序契约（card_rules 全局约束）：落盘→meta 在前、卡片在后、handle 尾置。卡片行
``text`` 承载 reasonText+selectText，``say_to_user`` 同源供 agent 转述——toolresult
已承载的不另发纯文本行（硬规则 11）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from cli_timing import write_cli_output_line
from mclaw.shared.cm_cloud.card import Card
from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)

from services.person_search.state import write_ambiguity_state
from services.search.stdout_receipt import emit_agent_note
from services.stdout_receipt import Handle, emit_handle, ok_meta


def _unescape_literal_newlines(text: str) -> str:
    """接口文案字面 ``\\n`` 转真换行（整段透传会丢换行、选项挤成一行）。"""
    return text.replace('\\r\\n', '\n').replace('\\n', '\n')


#: 歧义回执固定追加的三选一搜索范围确认指引（references 同款模板搬进回执驱动
#: 遵循：候选人数只在 reasonText 文案里（歧义项 faceInfoList 为空），Python 不提取，
#: 由模型理解文案明晰 N 后替换为实际人数再告知用户；不能明晰人数不硬套模板）
_SCOPE_HINT = (
    '假如能明晰候选人数（N），请用以下用户友好提示向用户确认（N 替换为实际人数）：\n'
    '- 1、只找这N个人的合照（必须同框）\n'
    '- 2、包含这N个人（一起或单独出现都可以）\n'
    '- 3、只找其中某一个人的照片'
)


def _fetch_file_names(file_ids: List[str]) -> Dict[str, str]:
    """歧义卡参考图文件名富化（best-effort：失败回退「参考图」，不阻断交互）。"""
    try:
        from services.atomic.file_maps import get_file_info_map

        info_map = get_file_info_map(file_ids)
    except Exception:
        return {}
    return {fid: str((info or {}).get('name') or '') for fid, info in info_map.items()}


def emit_ambiguity(
    ambiguity_list: List[Any],
    *,
    query: str = '',
    file_ids: Optional[List[str]] = None,
    recognize_query: str = '',
    persist: bool = True,
) -> str:
    """歧义终态输出：落 ambiguity.jsonl → meta ok → ``:::selectFaceList`` 卡 → handle 尾行。

    - 落盘（``persist=True``，首跳 face/recognize 歧义用）：``op_xxxxxx/ambiguity.jsonl``
      （queryA + recognizeQuery + fileIds），返回 handle；写盘失败降级无 handle
      （不阻断交互，仍发卡）。``persist=False``（merge/image 首页歧义守卫用，待定边案）：
      只发卡、不落盘、返 ''。
    - ``say_to_user``：接口 ``reason.reasonText`` + ``reason.selectText`` 原样（经
      ``_unescape_literal_newlines``，空也照传）+ ``_SCOPE_HINT`` 确认指引固定追加
      （模型理解文案明晰候选人数后替换 N 再告知用户；接口文案空时仅指引）；
      卡片行 ``text`` 不追加，保持接口文案原样。
    - 卡片行 ``{fileId, name, text}``（name 批量富化、查不到回退「参考图」；
      text = reasonText+selectText）；无候选人脸行时（仅顶层 ambiguityFlag）不发卡。
    - handle 尾行 ``params.ambiguity=true``（需澄清标志，成功终态为 false）；无落盘
      （降级/persist=False）则无 handle 行。
    """
    # ── 落盘歧义态（queryA + recognizeQuery + fileIds 快照）供下轮 --from 导入 ──
    ambiguity_handle = ''
    if persist:
        try:
            session = OrganizeSession.create()
            ambiguity_handle = write_ambiguity_state(
                session, query=query, recognize_query=recognize_query,
                file_ids=list(file_ids or []),
            )
        except (OrganizeSessionError, OSError):
            # 写盘失败：不阻断交互，降级为无 handle（仍发卡让用户选脸；下轮无 --from 可承接）
            ambiguity_handle = ''

    # ── reasonText + selectText 原样进 say_to_user（空也照传，不兜底固定文案）──
    reason_text = ''
    select_text = ''
    if ambiguity_list:
        reason = getattr(ambiguity_list[0], 'reason', None)
        if reason is not None:
            reason_text = _unescape_literal_newlines(
                str(getattr(reason, 'reason_text', '') or '')
            )
            select_text = _unescape_literal_newlines(
                str(getattr(reason, 'select_text', '') or '')
            )
    card_text = '\n'.join(p for p in (reason_text, select_text) if p)

    # ── say_to_user = 接口文案 + 三选一提示固定追加（卡片 text 不动）──
    say_text = f'{card_text}\n{_SCOPE_HINT}' if card_text else _SCOPE_HINT

    # ── 卡片行（fileId 取自 ambiguity_list；name 批量富化）──
    card_file_ids = [
        fid for fid in (
            str(getattr(item, 'file_id', '') or '') for item in (ambiguity_list or [])
        ) if fid
    ]
    name_map = _fetch_file_names(card_file_ids) if card_file_ids else {}
    rows: List[Dict[str, Any]] = [
        {'fileId': fid, 'name': name_map.get(fid) or '参考图', 'text': card_text}
        for fid in card_file_ids
    ]

    ok_meta('person-search', say_to_user=say_text)
    if not rows:
        return ambiguity_handle
    # meta（resultType/summary）走公共库 CARD_META_BY_CLI['person_search'] 配置
    for line in Card(
        'selectFaceList', rows, cli='person_search',
    ).generate():
        write_cli_output_line(line)
    # handle 尾行：params.ambiguity=true 标记需澄清（下轮 --select-faces --from 承接）；
    # 行序同 search 终态（卡片 → agent_note → handle 尾置，agent_note 先消费防 main.py
    # finally 补到 handle 之后）；写盘失败降级（无 handle）不发此行
    if ambiguity_handle:
        emit_agent_note()
        emit_handle(Handle(id=ambiguity_handle, params={'ambiguity': True}))
    return ambiguity_handle


__all__ = ['emit_ambiguity']
