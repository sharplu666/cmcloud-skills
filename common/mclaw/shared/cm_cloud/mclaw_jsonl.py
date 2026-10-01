#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""卡片化 toolResult 旁路持久化。

将含 ``:::`` 的完整 CLI stdout 追加写入旁路文件，供对账 / 历史卡片恢复。
旁路失败只返回 ``False``，**绝不抛异常**，不中断 CLI。

用法::

    from mclaw.shared.cm_cloud.mclaw_jsonl import append_mclaw_tool_result

    # flush stdout 之后调用（id 默认读环境变量）
    append_mclaw_tool_result(emitted_stdout)

    # 或显式传入
    append_mclaw_tool_result(emitted_stdout, session_id=sid, tool_call_id=tid)

落盘路径::

    /home/node/.openclaw/agents/main/sessions/<sessionId>.mclaw.jsonl

环境变量::

    MCLAW_SESSION_ID      会话 id（文件名 stem，通常为 UUID）
    MCLAW_TOOL_CALL_ID    工具调用 id

记录内容为 flush 后的完整 stdout（可含 timing / failapi / 提示文案 / 卡片围栏）。

并发：同一 ``sessionId`` 文件用 ``fcntl.flock(LOCK_EX)`` 串行化追加，
避免多进程并行写导致 JSONL 行交叉。
"""

from __future__ import annotations

try:
    import fcntl  # POSIX 文件锁；Windows 上退化为不加锁（旁路文件非必需一致性）
except ImportError:  # pragma: no cover - Windows 兼容
    class _NoLock:
        LOCK_SH = 1
        LOCK_EX = 2
        LOCK_NB = 4
        LOCK_UN = 8

        @staticmethod
        def flock(fd, operation):
            return None

    fcntl = _NoLock()
import json
import os
import re
from pathlib import Path
from typing import Any, Optional, Tuple

MCLAW_SESSION_ID_ENV = 'MCLAW_SESSION_ID'
MCLAW_TOOL_CALL_ID_ENV = 'MCLAW_TOOL_CALL_ID'

# 与主会话 jsonl 同目录（OpenClaw 容器固定路径）
SESSIONS_DIR = Path('/home/node/.openclaw/agents/main/sessions')

# sessionId 仅允许安全文件名字符（UUID / 常见 stem）
_SAFE_SESSION_ID = re.compile(r'^[A-Za-z0-9._-]+$')


def resolve_mclaw_persist_context() -> Optional[Tuple[str, str]]:
    """从环境变量读取 ``(session_id, tool_call_id)``；缺一则返回 ``None``。"""
    session_id = (os.getenv(MCLAW_SESSION_ID_ENV) or '').strip()
    tool_call_id = (os.getenv(MCLAW_TOOL_CALL_ID_ENV) or '').strip()
    if not session_id or not tool_call_id:
        return None
    return session_id, tool_call_id


def mclaw_jsonl_path(session_id: str) -> Path:
    """``SESSIONS_DIR / <sessionId>.mclaw.jsonl``。"""
    return SESSIONS_DIR / f'{session_id}.mclaw.jsonl'


def contains_card_fence(text: str) -> bool:
    """是否包含 ``:::`` 卡片围栏。"""
    return isinstance(text, str) and ':::' in text


def _is_safe_session_id(session_id: str) -> bool:
    return bool(session_id) and _SAFE_SESSION_ID.fullmatch(session_id) is not None


def _resolve_ids(
    session_id: Optional[str],
    tool_call_id: Optional[str],
) -> Optional[Tuple[str, str]]:
    """显式参数优先，缺省回落到环境变量；仍缺一则 ``None``。"""
    sid = (session_id or '').strip() or (os.getenv(MCLAW_SESSION_ID_ENV) or '').strip()
    tid = (tool_call_id or '').strip() or (os.getenv(MCLAW_TOOL_CALL_ID_ENV) or '').strip()
    if not sid or not tid:
        return None
    return sid, tid


def _append_jsonl_line(path: Path, line: str) -> None:
    """排他锁下追加一行（含换行）。关闭 fd 时也会释放锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = line if line.endswith('\n') else f'{line}\n'
    with path.open('a', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(payload)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def append_mclaw_tool_result(
    tool_result: str,
    *,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> bool:
    """追加一行 ``{"toolCallId", "toolResult"}`` 到旁路 jsonl。

    返回 ``True`` 表示已写入；无卡片围栏 / 缺 id / 非法 sessionId / 任意失败
    均返回 ``False``（不抛异常）。

    同一 ``sessionId`` 文件跨进程追加经 ``fcntl.flock`` 串行化。
    """
    try:
        if not contains_card_fence(tool_result):
            return False

        ids = _resolve_ids(session_id, tool_call_id)
        if ids is None:
            return False
        sid, tid = ids
        if not _is_safe_session_id(sid):
            return False

        line = json.dumps(
            {'toolCallId': tid, 'toolResult': tool_result},
            ensure_ascii=False,
        )
        _append_jsonl_line(mclaw_jsonl_path(sid), line)
        return True
    except Exception:
        return False


def persist_flushed_stdout(emitted: Any = None) -> bool:
    """CLI ``flush`` 后的旁路入口。

    非字符串 / 无围栏 / 缺 id / 写盘失败均返回 ``False``，**不抛异常**，
    调用方无需再包一层 ``try/except``。
    """
    try:
        text = emitted if isinstance(emitted, str) else ''
        return bool(append_mclaw_tool_result(text))
    except Exception:
        return False


__all__ = [
    'MCLAW_SESSION_ID_ENV',
    'MCLAW_TOOL_CALL_ID_ENV',
    'SESSIONS_DIR',
    'resolve_mclaw_persist_context',
    'mclaw_jsonl_path',
    'contains_card_fence',
    'append_mclaw_tool_result',
    'persist_flushed_stdout',
]
