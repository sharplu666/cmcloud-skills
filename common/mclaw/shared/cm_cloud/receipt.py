#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 stdout 回执契约：固定的 ``meta``(+``handle``) 两行壳 + 卡片 + agent_note。

各技能共用一份回执形状，
让模型不必先认 ``record`` 是哪一种再决定去哪个键取结论——成功/失败/让出都套同一个
``meta`` 信封，决策槽**非空才输出**（空槽省键，缺省 ≡ 空值，消费方一律 ``.get()`` 取）：

    {"record": "meta",          ← 第 1 行（恒在）
     "command": "organize_plan",
     "status": "ok",           ← ok / error / yielded
     "sayToUser": "已生成方案…", ← 转述给用户的话
     "next": {"submit": "..."},← 下一步可进行的命令（结构化，替代 [INFO] 裸 print；空不输出键）
     "needsConfirmation": {...},← 要先问用户吗（无则不输出键）
     "error": {...},            ← 出错详情（status=error 时才有；无则不输出键）
     "data": {...}}             ← 命令专属数据（空也输出 {}，可无条件读 data.xxx）
    {"record": "handle", "id": "op_a3f2c1/<文件>.jsonl", "params": {...}}   ← 第 2 行（有句柄时；id 携带 op 会话 id 加数据文件；params 非空才输出）
    <frontend_card name="...">:::…:::</frontend_card>        ← 卡片通道（按需）
    <agent_note source="mclaw">…</agent_note>                ← 有卡片时末行

设计依据见各技能 ``docs/cli_design.md`` §输出契约；与 ``cm_cloud_organize`` 的
``meta``+``handle`` 两行壳同构，但用 ``command``+``status``+``data`` 三槽适配多命令
（cm_cloud_organize 是单技能三子命令，用 ``stage`` 区分；本契约服务多技能多命令，用
``command`` 区分，``data`` 承载命令专属字段）。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# ── 退出码（shell 兜底；agent 一律以 meta.status 为准）──────────────────────────
EXIT_OK: int = 0
EXIT_ERROR: int = 1          # 业务/接口失败（status=error）
EXIT_USAGE: int = 2          # 参数错误（argparse 约定）
EXIT_NEEDS_CONFIRM: int = 3  # 需用户确认后带 --confirm 重跑（status=ok 但有 needsConfirmation）
EXIT_YIELDED: int = 4        # 全量拉取软预算让出（status=yielded，断点已落盘，原样重跑续拉）

#: 四词 status 协议（与既有回执一致，模型据此行动）
STATUS_OK: str = 'ok'
STATUS_ERROR: str = 'error'
STATUS_YIELDED: str = 'yielded'


@dataclass
class ErrorInfo:
    """出错详情（``meta.error``）。"""

    code: str = ''
    message: str = ''
    retryable: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'message': self.message,
            'retryable': self.retryable,
        }


@dataclass
class NeedsConfirmation:
    """需用户确认（``meta.needsConfirmation``）。organize plan 发；其余命令恒不发。"""

    reason: str
    say_to_user: str
    confirm_flag: str = ''

    def as_dict(self) -> Dict[str, str]:
        # confirmFlag 空不输出键（与 Handle.as_dict 空值省略同口径）
        d: Dict[str, str] = {
            'reason': self.reason,
            'sayToUser': self.say_to_user,
        }
        if self.confirm_flag:
            d['confirmFlag'] = self.confirm_flag
        return d


@dataclass
class Meta:
    """``meta`` 行（stdout 第 1 行，恒在）。空决策槽省键（2026-09-10 用户定案）。"""

    command: str
    status: str = STATUS_OK
    say_to_user: str = ''
    next_steps: Dict[str, str] = field(default_factory=dict)   # {step: 完整命令行}
    needs_confirmation: Optional[NeedsConfirmation] = None
    error: Optional[ErrorInfo] = None
    data: Dict[str, Any] = field(default_factory=dict)         # 命令专属字段

    def as_dict(self) -> Dict[str, Any]:
        # 空槽省键（next 空 / needsConfirmation / error 为 None 不输出；缺省 ≡ 空值，
        # 消费方一律 .get() 取）；data 即使为空也写 {}（模型可无条件读 data.xxx）。
        out: Dict[str, Any] = {
            'record': 'meta',
            'command': self.command,
            'status': self.status,
            'sayToUser': self.say_to_user,
        }
        if self.next_steps:
            out['next'] = self.next_steps
        if self.needs_confirmation is not None:
            out['needsConfirmation'] = self.needs_confirmation.as_dict()
        if self.error is not None:
            out['error'] = self.error.as_dict()
        out['data'] = self.data
        return out


@dataclass
class Handle:
    """``handle`` 行（stdout 第 2 行，有句柄时才发）。"""

    id: str
    params: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        # params 空不输出键；params 内空值（''/None）键省略（缺省不回显空串，
        # 无信息的死键不进 toolresult，2026-09-03 用户定案）
        d: Dict[str, Any] = {'record': 'handle', 'id': self.id}
        params = {k: v for k, v in self.params.items() if v is not None and v != ''}
        if params:
            d['params'] = params
        return d


def _resolve_write_line(write_line) -> Any:
    """默认走公共库 cli_timing 的统一写出口（缓冲/直写自适应）；不可用时回退 print。"""
    if write_line is not None:
        return write_line
    try:
        from cli_timing import write_cli_output_line  # common_auth（运行期已注入 sys.path）
        return write_cli_output_line
    except ImportError:
        return lambda line: print(line, flush=True)


def _inject_error_context(meta: Meta) -> None:
    """失败时从 cli_trace 取主接口路径，注入 ``data.failedApi``（成功回执无操作）。"""
    if meta.status != STATUS_ERROR or meta.data.get('failedApi') is not None:
        return
    try:
        from cli_trace import get_last_api_path  # common_auth
    except ImportError:
        return
    api_path = (get_last_api_path() or '').strip()
    if api_path:
        meta.data['failedApi'] = api_path


def emit_meta(
    meta: Meta,
    *,
    handle: Optional[Handle] = None,
    write_line=None,
) -> None:
    """输出 ``meta`` 行（+ 可选 ``handle`` 行）。

    ``write_line`` 默认走 ``cli_timing.write_cli_output_line``（缓冲开启时暂存、flush
    时统一输出；未开启时直写 stdout），保证回执与卡片/agent_note 走同一出口、顺序正确。
    """
    _inject_error_context(meta)
    wl = _resolve_write_line(write_line)
    wl(json.dumps(meta.as_dict(), ensure_ascii=False))
    if handle is not None:
        wl(json.dumps(handle.as_dict(), ensure_ascii=False))


def emit_handle(handle: Handle, *, write_line=None) -> None:
    """单独输出 ``handle`` 行（meta 已先发、后续追加句柄时用）。"""
    wl = _resolve_write_line(write_line)
    wl(json.dumps(handle.as_dict(), ensure_ascii=False))


def emit_agent_note(*, write_line=None) -> None:
    """输出 ``<agent_note>``（有卡片时由前端渲染，提示模型回复须纯文本）。

    复用同包 ``card_meta.card_end_note``：进程内只要经 ``frontend_card_tags`` 登记过
    卡片，本函数即发出末行说明；未登记卡片时返回空串（不输出）。
    """
    try:
        from mclaw.shared.cm_cloud.card_meta import card_end_note
    except ImportError:
        return
    note = card_end_note()
    if not note:
        return
    wl = _resolve_write_line(write_line)
    wl(note)


def exit_code(meta: Meta) -> int:
    """由 meta 推退出码（shell 兜底；agent 以 meta.status 为准）。"""
    if meta.status == STATUS_ERROR:
        return EXIT_ERROR
    if meta.status == STATUS_YIELDED:
        return EXIT_YIELDED
    if meta.needs_confirmation is not None:
        return EXIT_NEEDS_CONFIRM
    return EXIT_OK


__all__ = [
    'EXIT_OK',
    'EXIT_ERROR',
    'EXIT_USAGE',
    'EXIT_NEEDS_CONFIRM',
    'EXIT_YIELDED',
    'STATUS_OK',
    'STATUS_ERROR',
    'STATUS_YIELDED',
    'ErrorInfo',
    'NeedsConfirmation',
    'Meta',
    'Handle',
    'emit_meta',
    'emit_handle',
    'emit_agent_note',
    'exit_code',
]
