#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 空间日志辅助：把相册/回忆故事新增图片后的 id 追加写入 jsonl 文件。

与 ``common_auth/operation_log.py`` 的模块级状态机制不同，本模块无状态：
caller 在 ``Api.__init`` 时传入完整文件路径（或仅传入 ``operation`` 由本模块
按约定生成路径），``execute`` 成功后直接 append 一行 JSON。

写入成功后：
  - 通过 ``status_log`` 打印 ``保存AI空间动态：{record}`` 日志，``info_dict``
    携带 ``log_path`` 字段（值为相对路径，参照 ``operation_log`` 约定）。
  - 维护模块级状态 ``_ai_space_log_rel_paths``，供 ``mclaw/__init__.py``
    注册的 ``atexit`` 钩子在进程退出时向 stdout 输出
    ``<log_path>...</log_path>`` 标记。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, List, Optional

from mclaw.utils.logger import openclaw_logger, status_log
from mclaw.utils.settings import AiSpaceLogSettings


__all__ = [
    'append_ai_space_log',
    'append_ai_space_log_record',
    'get_ai_space_log_path_for_output',
    'reset_ai_space_log',
    'resolve_ai_space_log_path',
]


# 模块级状态：记录所有写入过的日志路径（去重），供 atexit 钩子输出 <log_path> 标记。
_ai_space_log_abs_paths: List[str] = []
_ai_space_log_rel_paths: List[str] = []


def _to_rel_path(abs_path: str) -> str:
    """workspace 绝对路径 → ``workspace/...`` 相对路径；非 workspace 路径原样返回。

    参照 ``common_auth/operation_log.py`` 的 ``_operation_log_rel_path`` 约定：
    剥离 workspace 根目录前缀，保留 ``workspace/`` 前缀作为逻辑相对路径标记。
    """
    if not abs_path:
        return abs_path
    p = os.path.abspath(abs_path)
    ws = str(AiSpaceLogSettings.WORKSPACE_DIR).rstrip('/') + '/'
    if p.startswith(ws):
        return 'workspace/' + p[len(ws):]
    return p


def _generate_log_filename(operation: str = '') -> str:
    """按 ``<operation>_<timestamp>.jsonl`` 生成日志文件名。

    命名规则参考 operation_log / batch_move 等约定：
      - ``operation`` 为空时回退到 ``{sessionId}_{uuid}.jsonl``；
      - ``timestamp`` 格式为 ``%Y%m%d%H%M%S``，取调用瞬间。
    """
    operation = str(operation or '').strip()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    if operation:
        return f'{operation}_{timestamp}.jsonl'
    return f"{os.getenv('sessionId', '')}_{timestamp}_{os.urandom(4).hex()}.jsonl"


def resolve_ai_space_log_path(
    log_path: Optional[str] = None,
    operation: str = '',
) -> str:
    """把 caller 传入的路径或操作名归一为完整绝对路径。

    Args:
        log_path: 完整文件路径（caller 负责，可为相对或绝对）。
            非空时直接返回该路径。
        operation: 操作名；``log_path`` 为空/None 时用于生成文件名
            ``<operation>_<timestamp>.jsonl``。

    Returns:
        ``<OPENCLAW_WORKSPACE>/dynamic_log/<YYYY-MM-DD>/<filename>.jsonl``
    """
    if log_path:
        return log_path
    date = datetime.now().strftime('%Y-%m-%d')
    log_dir = os.path.join(
        AiSpaceLogSettings.WORKSPACE_DIR,
        AiSpaceLogSettings.LOG_DIR_NAME,
        date,
    )
    return os.path.join(log_dir, _generate_log_filename(operation))


def reset_ai_space_log() -> None:
    """重置模块级状态。

    CLI 多次调用场景下，新命令开始前调用本函数，避免上一轮的 ``<log_path>``
    残留。
    """
    global _ai_space_log_abs_paths, _ai_space_log_rel_paths
    _ai_space_log_abs_paths = []
    _ai_space_log_rel_paths = []


def get_ai_space_log_path_for_output() -> List[str]:
    """返回所有写入过的相对路径；未写入过返回空列表。

    供 ``mclaw/__init__.py`` 注册的 ``atexit`` 钩子在进程退出时输出
    ``<log_path>...</log_path>`` 标记，与
    ``operation_log.get_operation_log_path_for_output`` 行为一致。
    """
    return list(_ai_space_log_rel_paths)


def append_ai_space_log_record(
    log_path: str,
    record: dict[str, Any],
    *,
    logger: Any = None,
) -> None:
    """把任意 dict 作为一行 JSON 追加写入 ``log_path``（通用「path + content」写入）。

    album/story/organize 等所有 AI 空间动态记录统一走本函数：
      - 建父目录（``os.makedirs(..., exist_ok=True)``）；
      - 以 append 模式写一行 ``json.dumps(record, ensure_ascii=False) + '\\n'``；
      - 把路径登记进模块级 ``_ai_space_log_abs/rel_paths``（去重），供退出钩子
        ``_print_ai_space_log_path`` 打印 ``<log_path>`` 标记；
      - 调 ``status_log`` 打印 ``保存AI空间动态：{record}``，``info_dict`` 带
        ``log_path`` 字段（值为相对路径）。

    Args:
        log_path: 完整文件路径（caller 负责，可由
            ``resolve_ai_space_log_path(operation=...)`` 生成）。空串或 ``record``
            为空时静默跳过。
        record: 任意业务记录 dict，原样序列化为 JSON 行。后续要往同一文件追加
            不同内容，再调一次本函数、传入同一 ``log_path`` 与新 dict 即可。
        logger: ``status_log`` 用的 logger；``None`` 用 ``openclaw_logger`` 兜底。
    """
    if not log_path or not record:
        return
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    with open(log_path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    global _ai_space_log_abs_paths, _ai_space_log_rel_paths
    abs_path = os.path.abspath(log_path)
    rel_path = _to_rel_path(abs_path)
    if rel_path not in _ai_space_log_rel_paths:
        _ai_space_log_abs_paths.append(abs_path)
        _ai_space_log_rel_paths.append(rel_path)
    status_log(
        msg=f'保存AI空间动态：{json.dumps(record, ensure_ascii=False)}',
        logger=logger or openclaw_logger,
        info_dict={'log_path': rel_path},
        server_type='SYNC',
    )


def append_ai_space_log(
    log_path: str,
    *,
    is_story: bool,
    album_id: str,
    name: str = '',
    record_type: str = '',
    logger: Any = None,
) -> None:
    """把一行 AI 空间动态记录追加写入 ``log_path`` 指向的 jsonl 文件。

    Args:
        log_path: 完整文件路径（caller 负责，可为相对或绝对路径）。
            空串或 ``album_id`` 为空时静默跳过。
        is_story: ``True`` → key 为 ``storyId``（回忆故事）；
            ``False`` → key 为 ``albumId``（普通相册）。
        album_id: 相册 ID 或回忆故事 ID。
        name: 相册/回忆故事名称；非空时写入 ``albumName`` / ``storyName``。
        record_type: 记录类型；非空时写入 ``type`` 字段，如 ``album`` / ``story``。
        logger: ``status_log`` 使用的 logger 实例。``None`` 时用
            ``openclaw_logger`` 兜底。caller（album API 子类）应传
            ``self.logger`` 以保持与基类日志链路一致。

    父目录不存在时自动创建（``os.makedirs(..., exist_ok=True)``）。

    写入成功后：
      - 更新模块级 ``_ai_space_log_abs_paths`` / ``_ai_space_log_rel_paths``；
      - 调用 ``status_log`` 打印 ``保存AI空间动态：{record}`` 日志，
        ``info_dict`` 携带 ``log_path`` 字段（值为相对路径）。
    """
    if not log_path or not album_id:
        return
    key = 'storyId' if is_story else 'albumId'
    name_key = 'storyName' if is_story else 'albumName'
    record: dict[str, Any] = {key: album_id}
    if name:
        record[name_key] = name
    if record_type:
        record['type'] = record_type
    # 建目录 / 写盘 / 路径追踪 / status_log 统一由通用原语完成
    append_ai_space_log_record(log_path, record, logger=logger)
