#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI生图 任务状态查询脚本（用户主动调用的轮询能力，兜底用）

仅当用户主动想查询某个生图任务的结果时调用；**绝不自动触发**。
配合 main.py：main.py 默认 ~120s 内未完成会返回 taskId，用户凭 taskId
在此主动轮询取结果。

调用方式：
# 单次查询（仅看一眼当前状态，不内部循环）
python dev/skills/image_tool/ai_image_generate/scripts/status.py --task-id "<taskId>"

# 有界内部轮询（最多等 --max-wait 秒，默认 480s）
python dev/skills/image_tool/ai_image_generate/scripts/status.py --task-id "<taskId>" --wait

# 分批任务批量续查：一次传多个 taskId，成功结果汇总为一组卡片输出
python dev/skills/image_tool/ai_image_generate/scripts/status.py --task-id "<taskId1>" "<taskId2>" --wait

# 归档目录与 main.py 保持一致：未传 --save-dir-id 时保存到会话默认目录
# （/AI空间/<APP>/对话文件 下按会话生成的目录），不再按 query 建子目录
python dev/skills/image_tool/ai_image_generate/scripts/status.py --task-id "<taskId>" --wait
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
_AUTH_ROOT = os.path.join(_SCRIPT_DIR, "..", "..", "..", "common_auth")
if _AUTH_ROOT not in sys.path:
    sys.path.insert(0, _AUTH_ROOT)
_MCLAW_ROOT = os.path.join(_SCRIPT_DIR, "..", "..", "..", "common")
if _MCLAW_ROOT not in sys.path:
    sys.path.insert(0, _MCLAW_ROOT)

from mclaw.api.auth import get_auth_header, get_skill_auth

from mclaw.api import ApiDispatcher
from mclaw.api.image_tool.ai_image_generate_api import (
    AiImageGenerateApi,
    AiImageGenerateRequest,
)
from mclaw.shared.image_tools import (
    emit_big_image_list_card,
    emit_file_path_list_card,
    ensure_session_default_dir,
    extract_poll_result,
    move_result_to_directory,
    resolve_session_from_env,
)
from cli_timing import (
    clear_api_timings,
    flush_cli_output_buffer,
    start_cli_output_buffer,
    write_cli_output_line,
)
from mclaw.shared.cm_cloud.mclaw_jsonl import persist_flushed_stdout
import operation_log

_auth_cfg = get_skill_auth()
HOST = _auth_cfg.host
OUTPUT_DIR = os.getenv("TEMP_OUTPUT_DIR", "/home/node/.openclaw/workspace/")

# 单次轮询（无 --wait）时的最大轮询次数
_SINGLE_QUERY_ATTEMPTS = 1

_VERBOSE = False


def _print(*args: Any, **kwargs: Any) -> None:
    if _VERBOSE:
        print(*args, **kwargs)


# ──────────────────────────── 主流程 ────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AI生图 任务状态查询（用户主动轮询）")
    parser.add_argument("--task-id", nargs="+", required=True,
                        help="待查询的任务 ID（来自 main.py 回执）；支持一次传多个（分批任务批量续查），空格分隔")
    parser.add_argument(
        "--save-dir-id", default=None,
        help="结果保存目录 fileId；未传则用会话默认目录",
    )
    parser.add_argument(
        "--save-dir-name", default=None,
        help="（已废弃，传入将被忽略）归档目录统一为会话默认目录，不再按 query 建子目录",
    )
    parser.add_argument(
        "--no-archive", action="store_true",
        help="跳过归档：不移动结果、不输出 filePathList 卡片，仅输出 bigImageList 结果卡；"
        "须与 main.py 当时的 --no-archive 保持一致（与 --save-dir-id 同传时以 --save-dir-id 为准）",
    )
    parser.add_argument("--wait", action="store_true", help="有界内部轮询（最多 --max-wait 秒）；不传则单次查询")
    parser.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒数（仅 --wait 生效）")
    parser.add_argument("--max-wait", type=int, default=480, help="有界轮询最长等待秒数（仅 --wait 生效）")
    parser.add_argument("--verbose", action="store_true", help="输出详细信息")
    args = parser.parse_args()

    global _VERBOSE
    _VERBOSE = args.verbose

    clear_api_timings()
    operation_log.init_operation_log(command="ai_image_generate_status")
    start_cli_output_buffer()

    try:
        _run_impl(args)
    finally:
        persist_flushed_stdout(
            flush_cli_output_buffer(
                log_path=operation_log.get_operation_log_path_for_output(),
                log_path_position="end",
            )
        )


def _run_impl(args) -> None:
    raw_session, session_id = resolve_session_from_env(required=True, error_cls=ValueError)
    _print(f"current session_id={session_id}")

    # 仅轮询（不重新提交）：直接用现有 AiImageGenerateApi 的 _poll，复用终态判定 3/4/5。
    # _poll 只读 request 的 poll_interval / poll_max_attempts，故用一个占位 request 承载轮询参数。
    # send_type 为必填字段，这里仅作占位（不会进入 payload），填 3=fileId。
    api = AiImageGenerateApi(host=HOST, auth_fn=get_auth_header)
    max_attempts = max(1, int(args.max_wait // max(args.interval, 0.1))) if args.wait else _SINGLE_QUERY_ATTEMPTS
    dummy = AiImageGenerateRequest(
        query="__status_poll__",
        send_type=3,
        poll_interval=args.interval,
        poll_max_attempts=max_attempts,
    )

    # 支持一次查询多个 taskId（main.py 分批任务的批量续查）：逐任务轮询，成功结果汇总为一组卡片
    success_ids: List[str] = []
    success_infos: Dict[str, Dict[str, Any]] = {}
    still_pending: List[str] = []
    failed_msgs: List[str] = []

    for task_id in args.task_id:
        resp = api._poll(task_id, dummy, return_task_id=True)
        if resp.is_success:
            _print(json.dumps(extract_poll_result(resp), ensure_ascii=False, indent=2))
            for info in resp.file_info_list or []:
                if isinstance(info, dict) and info.get("fileId"):
                    success_ids.append(info["fileId"])
                    success_infos[info["fileId"]] = info
        elif resp.status == 2:  # 仍处理中：暂停自动轮询，交还用户决定是否再查
            still_pending.append(task_id)
        else:  # status in (4 失败, 5 过期)
            failed_msgs.append(f"taskId={task_id} status={resp.status}({resp.status_text})")

    if success_ids:
        _emit_results(
            success_ids, success_infos, args.save_dir_id, raw_session,
            no_archive=args.no_archive,
        )

    for task_id in still_pending:
        print(f"任务仍在生成中，已暂停自动轮询，可稍后再次查询。taskId={task_id}", flush=True)

    if failed_msgs:
        if not success_ids and not still_pending:
            raise RuntimeError(f"异步任务未成功完成：{'；'.join(failed_msgs)}")
        print(f"警告：{'；'.join(failed_msgs)}", flush=True)


def _emit_results(
    result_file_ids: List[str],
    result_file_infos: Dict[str, Dict[str, Any]],
    save_dir_id: Optional[str],
    raw_session: str,
    no_archive: bool = False,
) -> None:
    """结果 fileId 列表 → 移动到目标目录 → 直出 filePathList + bigImageList 渲染卡。

    未传 save_dir_id 时归档到会话默认目录（/AI空间/<APP>/对话文件 下按会话生成的目录）。
    no_archive=True（且未传 save_dir_id）时跳过归档：不建目录、不移动、不出 filePathList 卡，仅输出
    bigImageList 结果卡（结果 fileId 供后续技能承接）。
    """
    dispatcher = ApiDispatcher(host=HOST, auth_fn=get_auth_header)

    if save_dir_id:
        target_dir_id = save_dir_id
        target_dir_path = ""
    elif no_archive:
        write_cli_output_line("已跳过归档（--no-archive），结果文件保留在生成位置")
        emit_big_image_list_card(result_file_ids, cli='ai_image_generate')
        return
    else:
        target_dir_id, target_dir_path = ensure_session_default_dir(raw_session)

    dir_id, dir_path = "", ""
    if target_dir_id:
        write_cli_output_line(f"移动结果文件到 {target_dir_path or target_dir_id} ...")
        move_result = move_result_to_directory(result_file_ids, target_dir_id, dispatcher)
        write_cli_output_line(f"移动完成: {move_result['message']}")
        operation_log.append_ai_moved_result_logs(result_file_infos, move_result)
        dir_id = move_result.get("targetDirFileId") or target_dir_id
        dir_path = move_result.get("targetPath") or target_dir_path
    else:
        write_cli_output_line("未取得目标目录，结果文件保留在生成位置，跳过归档")

    if dir_id:
        emit_file_path_list_card(dir_path, dir_id, cli='ai_image_generate')
    emit_big_image_list_card(result_file_ids, cli='ai_image_generate')


if __name__ == "__main__":
    main()
