#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI Session 合法性校验与规范化（mclaw 共用规范源）。

本模块是 ``agent:main:xx`` 形态 Session 参数的唯一规范实现；历史位置
``common_auth/session_cli_validate.py`` 与 ``mclaw/shared/ai_space/`` 均已降级为
re-export 垫片，指向此处，逻辑保持一致。

对外主入口：
  - :func:`validate_cli_session_raw` —— 校验 Session 非空且可解析。
  - :func:`extract_session_id` —— 提取会话标识（``agent:main:xx`` → ``xx``）。

其余能力（cron / share_cron 解析、目录安全规范化）保留供 ``session_folder`` 等
内部编排复用。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Literal, Optional, TextIO, Tuple

_SESSION_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')

_SESSION_FORMAT_HINT = (
    'Session 须为 agent:main:... / main:... / cron:... 等合法形态。'
)
SESSION_FORMAT_HINT = _SESSION_FORMAT_HINT


@dataclass(frozen=True)
class ParsedCliSession:
    kind: Literal['cron', 'chat', 'share_cron']
    body: str


class MclawEnvError(ValueError):
    """MCLAW 环境变量不合法（缺失或格式非法）。"""


def _parse_cron_job_id(body: str) -> str:
    """从 cron Session body 提取 jobId（忽略 :run:runId 后缀）。"""
    text = str(body or '').strip()
    if ':run:' in text:
        return text.split(':run:', 1)[0].strip()
    return text.split(':', 1)[0].strip()


def _resolve_cron_job_name(job_id: str) -> str:
    try:
        with open('/home/node/.openclaw/cron/jobs.json', 'r', encoding='utf-8') as f:
            whole = json.load(f)
        for job in whole.get('jobs') or []:
            if job.get('id') == job_id:
                return str(job.get('name') or '').strip()
    except Exception:
        pass
    return ''


def _resolve_share_cron_job_id(share_cron_token: str) -> Tuple[str, str]:
    """聚合型定时任务：扫描 jobs.json，按 sessionTarget 是否包含 share_cron token 反查 jobId。

    聚合任务的真正 jobId 不在 Session 字符串里，而是记录在 jobs.json 某条 job 的
    ``sessionTarget``（形如 ``session:share_cron_<shareId>``）中。这里遍历所有 job，
    找到 ``sessionTarget`` 包含该 token 的那条，返回 ``(job_id, job_name)``；
    未命中或读取异常时返回 ``('', '')``，交由调用方兜底。
    """
    token = str(share_cron_token or '').strip()
    if not token:
        return '', ''
    try:
        with open('/home/node/.openclaw/cron/jobs.json', 'r', encoding='utf-8') as f:
            whole = json.load(f)
        for job in whole.get('jobs') or []:
            session_target = str(job.get('sessionTarget') or '')
            if token in session_target:
                job_id = str(job.get('id') or '').strip()
                if job_id:
                    return job_id, str(job.get('name') or '').strip()
    except Exception:
        pass
    return '', ''


def _require_session_body(body: str, *, label: str = 'Session') -> str:
    text = str(body or '').strip()
    if not text:
        raise ValueError(f'{label} 无效：标识不能为空。{_SESSION_FORMAT_HINT}')
    return text


def _require_allowed_session_prefix(raw: str) -> None:
    if raw.startswith('main:') or raw.startswith('cron:'):
        return
    if raw == 'agent:main' or raw.startswith('agent:main:'):
        return
    raise ValueError(f'Session 无效：{_SESSION_FORMAT_HINT}')


def parse_cli_session_raw(value: str) -> ParsedCliSession:
    """解析 CLI Session，识别定时任务与普通对话。"""
    raw = str(value or '').strip()
    if not raw:
        raise ValueError(f'未传 Session：{_SESSION_FORMAT_HINT}')

    _require_allowed_session_prefix(raw)

    s = raw[6:] if raw.startswith('agent:') else raw

    if s in {'main', 'main:cron', 'cron'}:
        raise ValueError(f'Session 无效：缺少会话或任务标识。{_SESSION_FORMAT_HINT}')

    if s.startswith('main:cron:'):
        body = _require_session_body(s[len('main:cron:'):], label='定时任务')
        return ParsedCliSession('cron', body)

    if s.startswith('cron:'):
        body = _require_session_body(s[len('cron:'):], label='定时任务')
        return ParsedCliSession('cron', body)

    # 聚合型定时任务：body 形如 share_cron_<shareId>，真正的 jobId 需扫描 jobs.json 反查
    if s.startswith('main:share_cron_'):
        body = _require_session_body(s[len('main:'):], label='聚合定时任务')
        return ParsedCliSession('share_cron', body)

    if s.startswith('main:'):
        body = _require_session_body(s[len('main:'):])
        return ParsedCliSession('chat', body)

    raise ValueError(f'Session 无效：缺少会话或任务标识。{_SESSION_FORMAT_HINT}')


def validate_cli_session_raw(value: str, *, error_cls: type[Exception] = ValueError) -> None:
    """校验 CLI 传入的 Session 非空且可解析。

    合法返回 ``None``；非法抛 ``error_cls``（默认 ``ValueError``）。
    """
    try:
        parse_cli_session_raw(value)
    except ValueError as exc:
        raise error_cls(str(exc)) from exc


MCLAW_CURRENT_SESSION_ENV = 'MCLAW_CURRENT_SESSION'
# 与 mclaw_jsonl 同名常量；此处自声明避免循环依赖
MCLAW_TOOL_CALL_ID_ENV = 'MCLAW_TOOL_CALL_ID'
MCLAW_SESSION_ID_ENV = 'MCLAW_SESSION_ID'
OPENCLAW_ID_ENV = 'OPENCLAW_ID'
_SESSION_ENV_HINT = (
    f'请确认运行环境已设置 {MCLAW_CURRENT_SESSION_ENV}。'
)


def format_runtime_env_line() -> str:
    """一行可读诊断：工具调用标识。"""
    tool_call_id = (os.getenv(MCLAW_TOOL_CALL_ID_ENV) or '').strip() or '(unset)'
    return f'[INFO] {MCLAW_TOOL_CALL_ID_ENV}={tool_call_id}'


def emit_runtime_env(*, file: Optional[TextIO] = None) -> None:
    """向 CLI 输出打印运行时会话相关环境变量（便于对照被忽略的 ``--session``）。"""
    print(format_runtime_env_line(), file=file or sys.stdout, flush=True)


def resolve_current_session(
    *,
    required: bool = True,
    error_cls: type[Exception] = MclawEnvError,
) -> str:
    """从环境变量 ``MCLAW_CURRENT_SESSION`` 解析当前 Session。

    CLI 传入的 ``--session`` / 位置参数 ``session`` 应由调用方忽略（仅保留兼容）。

    - ``required=True``：未设置或格式非法时抛 ``error_cls``（缺省 ``MclawEnvError``）
    - ``required=False``：未设置或非法时返回 ``''``
    """
    raw = (os.getenv(MCLAW_CURRENT_SESSION_ENV) or '').strip()
    if not raw:
        if required:
            raise error_cls(f'未设置当前会话：{_SESSION_ENV_HINT}')
        return ''
    try:
        validate_cli_session_raw(raw, error_cls=ValueError)
    except ValueError as exc:
        if required:
            raise error_cls(f'{exc} {_SESSION_ENV_HINT}') from exc
        return ''
    return raw


def extract_session_id(value: str, *, error_cls: type[Exception] = ValueError) -> str:
    """提取 CLI Session 的会话标识：``agent:main:xx`` → ``xx``。

    复用 :func:`parse_cli_session_raw` 做格式校验后返回 ``parsed.body``：
      - 普通对话 ``agent:main:xx`` / ``main:xx`` → ``xx``
      - 定时任务 → cron body（jobId，可能带 ``:run:runId``）
      - 聚合任务 → ``share_cron_<shareId>`` token

    与 :func:`normalize_cli_session_id` 的区别：本函数只取原始标识，不做云盘目录
    非法字符替换、不展开 cron 任务名。非法 Session 抛 ``error_cls``。
    """
    try:
        parsed = parse_cli_session_raw(value)
    except ValueError as exc:
        raise error_cls(str(exc)) from exc
    return parsed.body


def extract_session_body(value: str, *, error_cls: type[Exception] = ValueError) -> str:
    """剥掉 Session 外壳前缀（``agent:`` / ``main:``），返回其余全部原样内容。

    ``agent:main:xx`` → ``xx``；``agent:main:cron:<jobId>:run:<runId>`` →
    ``cron:<jobId>:run:<runId>``。仅剥壳不解析：cron / share_cron 段与
    ``:run:`` 后缀原样保留，供提交接口透传完整会话标识。非法形态抛
    ``error_cls``（校验复用 :func:`parse_cli_session_raw`）。
    """
    raw = str(value or '').strip()
    try:
        validate_cli_session_raw(raw, error_cls=ValueError)
    except ValueError as exc:
        raise error_cls(str(exc)) from exc
    s = raw[6:] if raw.startswith('agent:') else raw
    return s[5:] if s.startswith('main:') else s


def normalize_cli_session_id(value: str, *, error_cls: type[Exception] = ValueError) -> str:
    """将原始 Session 转为云盘目录安全的会话 ID。"""
    try:
        parsed = parse_cli_session_raw(value)
    except ValueError as exc:
        raise error_cls(str(exc)) from exc

    if parsed.kind == 'cron':
        job_id = _parse_cron_job_id(parsed.body)
        # 任务名从 jobs.json 按 jobId 查找，不从 Session 解析
        job_name = _resolve_cron_job_name(job_id) or '定时任务'
        normalized = f'{job_id}-{job_name}'
    elif parsed.kind == 'share_cron':
        # 聚合任务 jobId 由 jobs.json 的 sessionTarget 反查；未命中时回退用 share_cron token
        job_id, job_name = _resolve_share_cron_job_id(parsed.body)
        job_name = job_name or '定时任务'
        seg = job_id or parsed.body
        normalized = f'{seg}-{job_name}'
    else:
        normalized = parsed.body

    normalized = _SESSION_INVALID_CHARS.sub('-', normalized).strip()
    if not normalized:
        raise error_cls(f'Session 无效或为空：{_SESSION_FORMAT_HINT}')
    return normalized


# 无下划线公共别名，便于外部按需复用 cron 解析能力（保留原 _ 命名以兼容内部调用）
parse_cron_job_id = _parse_cron_job_id
resolve_cron_job_name = _resolve_cron_job_name
resolve_share_cron_job = _resolve_share_cron_job_id
