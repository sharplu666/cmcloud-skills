#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 stdout 回执输出：薄封装公共库 ``mclaw.shared.cm_cloud.receipt``。

本文件只做两件事：
  1. 引入公共库的固定 ``meta``(+``handle``) 两行壳 + 退出码常量；
  2. 提供业务侧便捷构造（``ok_meta`` / ``error_meta`` / ``yielded_meta``），
     把「命令名 + 说给用户的话 + 下一步 + 命令专属数据」组装成 ``Meta`` 并输出。

回执形状见 ``mclaw.shared.cm_cloud.receipt`` 模块 docstring；设计决策见
``docs/cli_design.md`` §输出契约。卡片块（``<frontend_card>``）由各 service 经公共库
``preview_cards``/``cli_cards`` 生成、``write_cli_output_line`` 实时直打（main.py tee
模式：print+flush 即时可见并收集全文）；``<agent_note>`` 由 main.py 收尾统一补发
（公共库 ``card_meta`` 的 atexit 钩子仅兜底），service 层只发 meta。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cli_timing import write_cli_output_line
from mclaw.shared.cm_cloud.receipt import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_YIELDED,
    ErrorInfo,
    Handle,
    Meta,
    NeedsConfirmation,
    emit_handle,
    emit_meta,
)
from mclaw.shared.progress import ProgressRecord

__all__ = [
    'STATUS_ERROR',
    'STATUS_OK',
    'STATUS_YIELDED',
    'ErrorInfo',
    'Handle',
    'Meta',
    'NeedsConfirmation',
    'emit_handle',
    'emit_meta',
    'ok_meta',
    'error_meta',
    'yielded_meta',
    'progress_resumed',
    'progress_fetching',
    'progress_notice',
]


def ok_meta(
    command: str,
    *,
    say_to_user: str,
    next_steps: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    handle: Optional[Handle] = None,
    needs_confirmation: Optional[NeedsConfirmation] = None,
) -> None:
    """成功回执：``record=meta, status=ok``。

    - ``say_to_user``：转述给用户的结论（可润色，不改数字）。
    - ``next_steps``：下一步可进行的命令，``{step: 完整命令行}``；终态传 ``None``/``{}``。
    - ``data``：命令专属字段（counts / taskId / renderText / rootDirPath…）。
    - ``handle``：有句柄时附带 ``handle`` 行（organize plan / refine 产 handle）。
    - ``needs_confirmation``：需用户确认才继续（organize plan 提交前确认）；其余命令不传。
    """
    emit_meta(
        Meta(
            command=command,
            status=STATUS_OK,
            say_to_user=say_to_user,
            next_steps=dict(next_steps or {}),
            data=dict(data or {}),
            needs_confirmation=needs_confirmation,
        ),
        handle=handle,
    )


def error_meta(
    command: str,
    message: str,
    *,
    code: str = '',
    retryable: bool = False,
    data: Optional[Dict[str, Any]] = None,
    say: Optional[str] = None,
    next_steps: Optional[Dict[str, str]] = None,
) -> None:
    """失败回执：``record=meta, status=error, error={code,message,retryable}``。

    ``say_to_user``：USAGE 置空（参数错误 agent 自修，不念给用户）；其余失败与
    message 同文（agent 转述即可），传 ``say`` 时以 ``say`` 为准（面向用户的
    完整文案与 error.message 短句分离的场景）。``data`` 可装 ``failedApi`` 等
    （failedApi 由公共库 emit_meta 按需自动注入）。``next_steps``：失败后仍可
    执行的下一步命令（如 folder id 指路 search），``{step: 完整命令行}``；
    空不输出键。
    """
    emit_meta(
        Meta(
            command=command,
            status=STATUS_ERROR,
            say_to_user='' if code == 'USAGE' else (say if say is not None else message),
            error=ErrorInfo(code=code, message=message, retryable=retryable),
            next_steps=dict(next_steps or {}),
            data=dict(data or {}),
        )
    )


def yielded_meta(
    command: str,
    *,
    say_to_user: str,
    rerun_cmd: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """让出回执：``record=meta, status=yielded``（断点已落盘，原样重跑续拉）。

    ``next.rerun`` 承载「以完全相同的参数重跑」（替代旧 ``[INFO]`` 裸 print）。
    """
    emit_meta(
        Meta(
            command=command,
            status=STATUS_YIELDED,
            say_to_user=say_to_user,
            next_steps={'rerun': rerun_cmd},
            data=dict(data or {}),
        )
    )


# ── 全量续拉进度行（record=progress，长跑续拉的实时进度/提示）──────────────


def _emit_progress(status: str, say_to_user: str) -> None:
    """输出一条 progress record（复用公共库 ``ProgressRecord`` 4 字段）。

    计数（已拉取/总数/续装数）写进 ``say_to_user`` 自然语言，不单列结构化字段
    （硬规则 11：模型看到不改变决策，不输出）。
    """
    write_cli_output_line(
        ProgressRecord(
            status=status,
            stage='full_fetch',
            say_to_user=say_to_user,
        ).to_json_line()
    )


def progress_resumed(resumed_count: int, total: int) -> None:
    """断点装载进度：续拉起点，从游标继续。"""
    _ = total  # 续传报真实累计已拉取数、不带总数（2026-08-26 定案）；保留入参与 progress_fetching 同形
    _emit_progress(
        'in_progress',
        f'继续上次进度，已获取 {resumed_count} 条',
    )


def progress_fetching(fetched: int, total: int) -> None:
    """翻页中的节流进度：sayToUser 带冻结展示总数（2026-08-26 定案）。"""
    part = f'/{total}' if total else ''
    _emit_progress(
        'in_progress',
        f'搜索进行中：已获取 {fetched}{part} 条',
    )


def progress_notice(say_to_user: str) -> None:
    """非节流场景的提示性进度（游标失效自愈 / OOM 上限 / 断点写失败）。"""
    _emit_progress('in_progress', say_to_user)
