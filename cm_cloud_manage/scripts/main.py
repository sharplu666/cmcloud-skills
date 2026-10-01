#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国移动云盘 CLI 入口 —— cm_cloud_manage skill。

用法：``python3 main.py <子命令> [参数...]``，``python3 main.py <子命令> -h`` 查看帮助。
子命令实现位于 ``cli/``；Service 层见 ``services/``。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 公共库引导：common/ 与 common_auth/ 位于本技能上一级目录，
# 注册进 sys.path 后无需外部 PYTHONPATH 即可运行
_LIB_ROOT = Path(__file__).resolve().parents[2]
for _lib in (_LIB_ROOT / 'common', _LIB_ROOT / 'common_auth'):
    _s = str(_lib)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from cli import (
    parse_batch_rename_spec,
    parse_check_exists_specs,
    run_batch_check_exists,
    run_batch_copy,
    run_batch_get,
    run_batch_move,
    run_batch_rename,
    run_create_default_save_dir,
    run_dynamic,
    run_get_default_save_dir,
    run_get_path,
    run_mkdir,
    run_organize,
    run_person_search,
    run_play_media,
    run_refine,
    run_search,
    run_search_by_ids,
    run_search_transfer,
    run_semantic_search,
    run_upload,
    run_download,
)
from cli.cli_runtime import (
    BATCH_COPY_MOVE_MAX,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    WRITE_COMMANDS,
    clear_api_timings,
    exit_with_error,
    get_operation_log_path_for_output,
    init_operation_log,
)
from mclaw.shared.cm_cloud.card_meta import card_end_note
from mclaw.shared.cm_cloud.mclaw_jsonl import append_mclaw_tool_result
from mclaw.shared.cm_cloud.session_cli_validate import (
    MclawEnvError,
    format_runtime_env_line,
    resolve_current_session,
)
from services.stdout_receipt import error_meta
from cli.parser import (
    build_parser,
    normalize_cloud_parent_file_id,
    parse_csv_file_ids,
)
from cli_timing import (
    build_api_timing_record,
    build_failapi_record,
    flush_cli_output_tee,
    start_cli_output_tee,
)
from cm_cloud_auth import is_cm_cloud_debug
from utils import write_cli_output_line


def handle_upload(args):
    return run_upload(
        args.file_path,
        args.target_dir,
        session=args.session,
    )


def handle_download(args):
    return run_download(
        parse_csv_file_ids(args.file_ids),
        args.download_dir,
    )


def handle_batch_get(args):
    return run_batch_get(parse_csv_file_ids(args.file_ids, field_name='fileIds'))


def handle_get_path(args):
    return run_get_path(parse_csv_file_ids(args.file_ids, field_name='fileIds'))


def handle_batch_check_exists(args):
    return run_batch_check_exists(parse_check_exists_specs(args.specs))


def handle_create_default_save_dir(args):
    return run_create_default_save_dir(getattr(args, 'session', '') or '')


def handle_get_default_save_dir(args):
    return run_get_default_save_dir(getattr(args, 'session', '') or '')


def handle_batch_move(args):
    file_ids = parse_csv_file_ids(args.file_ids, field_name='fileIds')
    if len(file_ids) > BATCH_COPY_MOVE_MAX:
        exit_with_error(
            f'错误：单次批量移动最多 {BATCH_COPY_MOVE_MAX} 个文件，'
            f'当前 {len(file_ids)} 个超出上限。大批量文件整理请改用「云盘文件管理」整理流程。',
            code=EXIT_INPUT_ERROR,
        )
    return run_batch_move(
        file_ids,
        normalize_cloud_parent_file_id(args.to_parent_file_id),
        args.session,
    )


def handle_batch_copy(args):
    file_ids = parse_csv_file_ids(args.file_ids, field_name='fileIds')
    if len(file_ids) > BATCH_COPY_MOVE_MAX:
        exit_with_error(
            f'错误：单次批量复制最多 {BATCH_COPY_MOVE_MAX} 个文件，'
            f'当前 {len(file_ids)} 个超出上限。大批量文件整理请改用「云盘文件管理」整理流程。',
            code=EXIT_INPUT_ERROR,
        )
    return run_batch_copy(
        file_ids,
        normalize_cloud_parent_file_id(args.to_parent_file_id),
        args.session,
    )


def handle_mkdir(args):
    return run_mkdir(args.dir_path)


def handle_batch_rename(args):
    session = (args.session or '').strip()
    prs = [parse_batch_rename_spec(t) for t in args.specs]
    if not prs:
        exit_with_error('错误：请提供 FILEID:NAME 至少一项', code=EXIT_INPUT_ERROR)
    return run_batch_rename(prs, session)


COMMAND_HANDLERS = {
    'upload': handle_upload,
    'download': handle_download,
    'batch_get': handle_batch_get,
    'get_path': handle_get_path,
    'batch_check_exists': handle_batch_check_exists,
    'create_default_save_dir': handle_create_default_save_dir,
    'get_default_save_dir': handle_get_default_save_dir,
    'batch_copy': handle_batch_copy,
    'batch_move': handle_batch_move,
    'mkdir': handle_mkdir,
    'batch_rename': handle_batch_rename,
    'organize': run_organize,
    'refine': run_refine,
    'search': run_search,
    'semantic-search': run_semantic_search,
    'dynamic': run_dynamic,
    'search-by-ids': run_search_by_ids,
    'search-transfer': run_search_transfer,
    'person-search': run_person_search,
    'play_media': run_play_media,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command or args.command == 'help':
        parser.print_help()
        sys.exit(EXIT_OK)

    handler = COMMAND_HANDLERS.get(args.command)
    if handler is None:
        exit_with_error(f'错误：未知子命令 {args.command}', code=EXIT_INPUT_ERROR)

    # 入口统一校验业务会话（MCLAW_CURRENT_SESSION 鉴权硬依赖，全命令生效）；
    # 校验失败出 USAGE 回执后立即终止，后续逻辑不执行。
    start_cli_output_tee()
    try:
        resolve_current_session(required=True)
    except MclawEnvError as exc:
        error_meta(args.command, str(exc), code='USAGE')
        sys.exit(EXIT_INPUT_ERROR)

    clear_api_timings()
    if args.command in WRITE_COMMANDS:
        init_operation_log(command=args.command)
    # 首行诊断：实际生效的会话 / toolCallId（CLI --session 已忽略）
    write_cli_output_line(format_runtime_env_line())
    exit_code = EXIT_OK
    try:
        exit_code = handler(args)
    finally:
        # 尾部补发（相对顺序沿用缓冲期：timing(调试) → failapi → 写操作 log_path → 卡片防复述 note）
        if is_cm_cloud_debug():
            timing = build_api_timing_record()
            if timing:
                write_cli_output_line(json.dumps(timing, ensure_ascii=False))
        failapi = build_failapi_record()
        if failapi:
            write_cli_output_line(json.dumps(failapi, ensure_ascii=False))
        log_path = (
            get_operation_log_path_for_output()
            if args.command in WRITE_COMMANDS
            else None
        )
        if log_path:
            write_cli_output_line(f'<log_path>{log_path}</log_path>')
        end_note = card_end_note()
        if end_note:
            write_cli_output_line(end_note)
        emitted = flush_cli_output_tee()
        try:
            append_mclaw_tool_result(emitted)
        except Exception:
            # 旁路不得影响 CLI 退出；append 内部已兜底，此处再加一层
            pass
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
