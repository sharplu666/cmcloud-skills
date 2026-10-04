#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：search-by-ids —— 按 fileId 精确取文件详情（含 AI 分析信息）。

业务规则（与 references/SEARCH-FILE.md 一致，禁止自由发挥）：
  - 只收 ``--file-ids``（文件 fileId CSV，CLI 上限 ``SEARCH_BY_IDS_CLI_MAX_IDS``=20
    防参数幻觉；接口层 by-fileId fileList 上限 500 由 ``SEARCH_BY_IDS_MAX_IDS``
    对齐，两层并存）；其余参数 argparse 直接报 USAGE。
  - batchGet 校验 fileId 真实存在；任一不存在 → 整体拒绝（error 回执 message
    带全部缺失 id）。
  - ``type==folder`` 的项整体拒绝：message 列出 folder 名称/fileId，并提示去掉
    folder 重跑与「落盘后可用 refine、merge 等继续」；回执 ``next.search`` 给出
    ``search --scope-in <fileId>[,…] --recursive true --mode full`` 完整命令
    （先落盘 search.jsonl，支持断点续传）。
  - 最终结果经 search_by_fileId 一次全量取数（同步，无翻页、无卡片），
    落 ``op_<6位>/search.jsonl``（header searchKind=searchByFileIds）。

「异常→回执」映射内聚在本模块 run() 内（与 cli/search.py 同构）。
"""
from __future__ import annotations

import argparse
from typing import List, Tuple

from cli.cli_runtime import (
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
)
from services.search.degraded import describe_backend_error
from services.errors import CliValidationError, OperationServiceError
from services.search_by_ids import (
    FolderIdsRejected,
    resolve_file_ids,
    run_search_by_ids_search,
)
from services.stdout_receipt import error_meta
from utils.config import SEARCH_BY_IDS_CLI_MAX_IDS


def _parse_file_ids(raw: str) -> list:
    """--file-ids CSV → 去空去重列表；空值/超上限报 USAGE。"""
    text = str(raw or '').strip()
    if not text:
        raise CliValidationError('参数错误：--file-ids 必填（文件 fileId CSV，英文逗号分隔）')
    ids = [part.strip() for part in text.split(',')]
    ids = [fid for fid in ids if fid]
    if not ids:
        raise CliValidationError('参数错误：--file-ids 必填（文件 fileId CSV，英文逗号分隔）')
    unique = list(dict.fromkeys(ids))
    if len(unique) > SEARCH_BY_IDS_CLI_MAX_IDS:
        raise CliValidationError(
            f'参数错误：--file-ids 最多 {SEARCH_BY_IDS_CLI_MAX_IDS} 个，收到 {len(unique)} 个'
        )
    return unique


def _folder_reject_meta(folders: List[Tuple[str, str]]) -> None:
    """folder 拒绝回执：message 指路 + ``next.search`` 完整命令行。"""
    listing = '、'.join(f'{name}（fileId：{fid}）' for fid, name in folders)
    csv = ','.join(fid for fid, _name in folders)
    error_meta(
        'search-by-ids',
        f'以下 fileId 是文件夹，本命令仅支持文件：{listing}；'
        f'请从 --file-ids 中去掉文件夹后重跑；文件夹内容改用 search 拉取'
        f'（先落盘 search.jsonl，支持断点续传），落盘后如需与文件结果合并或'
        f'继续后续处理，可用 refine、merge 等',
        next_steps={
            'search': f'python3 main.py search --scope-in {csv} --recursive true --mode full'
        },
    )


def run(args: argparse.Namespace) -> int:
    """search-by-ids 入口：校验 → folder 检出拒绝 → 全量取数落盘回执。"""
    command = 'search-by-ids'
    try:
        input_ids = _parse_file_ids(getattr(args, 'file_ids', ''))
        file_ids = resolve_file_ids(input_ids)
        run_search_by_ids_search(file_ids)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except FolderIdsRejected as exc:
        _folder_reject_meta(exc.folders)
        return EXIT_BUSINESS_ERROR
    except OperationServiceError as exc:
        error_meta(command, exc.message, say=exc.say)
        return EXIT_BUSINESS_ERROR
    except RuntimeError as exc:
        _backend_hint = describe_backend_error(exc)
        if _backend_hint:
            error_meta(command, _backend_hint, code='BACKEND_DOWN', retryable=False)
        else:
            error_meta(command, f'服务端错误：{exc}；请停止并交用户决策，勿自动重试')
        return EXIT_BUSINESS_ERROR
    except Exception as exc:  # noqa: BLE001 兜底：未预期异常走内部错误回执
        error_meta(command, f'内部错误：{type(exc).__name__}: {exc}')
        return EXIT_INTERNAL_ERROR
    return EXIT_OK
