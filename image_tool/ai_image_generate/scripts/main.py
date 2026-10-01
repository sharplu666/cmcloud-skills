#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI生图独立调用脚本（主入口，端到端：提交 + 轮询到完成）

支持两种模式（同一接口）：
- 文生图：只传 --query，不传任何输入图；
- 图生图：传入至少一张输入图（--file-id），基于云盘图片做
  背景消除 / 图片合成 / 风格转换 等 Seedream 5.0 编辑。

调用方式（文生图，无输入图）：
python dev/skills/image_tool/ai_image_generate/scripts/main.py \
  --query "生成一张美丽的日落海景图" \
  --confirm

调用方式（云盘 fileId，sendType=3）：
python dev/skills/image_tool/ai_image_generate/scripts/main.py \
  --query "把后面的背景 p 掉" \
  --file-id "<输入图fileId>" \
  --confirm

批量处理：输入图超过单批上限（14 张）时自动分批——每批 ≤14 张、同一 query
逐批提交（服务端并行）、统一轮询、汇总为一组结果卡片输出。

长耗时任务：默认 ~120s 内未完成会返回 taskId（不自动触发轮询），
用户可主动用同目录 status.py --task-id <taskId> --wait 查询（支持多个 taskId）。
"""

import argparse
import base64
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
# common_auth 位于 dev/skills/common_auth/，scripts 位于 dev/skills/image_tool/ai_image_generate/scripts/
# 需回溯 3 层到 dev/skills/
_AUTH_ROOT = os.path.join(_SCRIPT_DIR, "..", "..", "..", "common_auth")
if _AUTH_ROOT not in sys.path:
    sys.path.insert(0, _AUTH_ROOT)
# 让 mclaw 包可 import（dev/skills/common/ 为 sys.path 根）
_MCLAW_ROOT = os.path.join(_SCRIPT_DIR, "..", "..", "..", "common")
if _MCLAW_ROOT not in sys.path:
    sys.path.insert(0, _MCLAW_ROOT)

from mclaw.api.auth import get_auth_header, get_skill_auth

from mclaw.api import ApiDispatcher
from mclaw.api.image_tool.ai_image_generate_api import (
    AiImageGenerateApi,
    AiImageGenerateRequest,
)
from mclaw.api.personal_saas.batch_get_api import BatchGetRequest
from mclaw.shared.image_tools import (
    emit_big_image_list_card,
    emit_file_path_list_card,
    ensure_session_default_dir,
    extract_poll_result,
    handle_sub_result_output,
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
from PIL import Image

_auth_cfg = get_skill_auth()
HOST = _auth_cfg.host
OUTPUT_DIR = os.getenv("TEMP_OUTPUT_DIR", "/home/node/.openclaw/workspace/")

# supplierType 固定为 7，与 ai_image_generate_api 默认值一致
SUPPLIER_TYPE = 7

# “AI生成”水印默认开启，不对外暴露 CLI 开关
WATERMARK = True

# ── 接口文档约束（严格校验）──
MAX_REF_IMAGES = 14                                   # 参考图数量上限
MAX_IMAGE_BYTES = 10 * 1024 * 1024                    # 单张参考图大小上限 10MB
MAX_IMAGE_PIXELS = 6000 * 6000                        # 单张参考图像素上限
SIZE_PIXELS_MIN = 2560 * 1440                         # size 总像素下限 3,686,400
SIZE_PIXELS_MAX = int(3072 * 3072 * 1.1025)           # size 总像素上限 10,408,236
ASPECT_MIN, ASPECT_MAX = 1 / 16, 16                   # size 宽高比范围
SEED_MIN, SEED_MAX = -1, 2147483647                   # seed 取值范围
SEQ_MAX_MIN, SEQ_MAX_MAX = 1, 15                      # sequentialMaxImages 取值范围
SEQ_TOTAL_MAX = 15                                    # 参考图数 + 生成数 上限
# base64 参考图支持的图片格式（小写）
ALLOWED_BASE64_FMTS = {"jpeg", "png", "webp", "bmp", "tiff", "gif"}
# PIL format → 文档要求的小写格式名
_PIL_FMT_MAP = {
    "JPEG": "jpeg", "JPG": "jpeg", "PNG": "png", "WEBP": "webp",
    "BMP": "bmp", "TIFF": "tiff", "GIF": "gif",
}

_VERBOSE = False


def _print(*args: Any, **kwargs: Any) -> None:
    if _VERBOSE:
        print(*args, **kwargs)


# ──────────────────────────── 本地图读取（PIL）+ 参数校验 ────────────────────────────


def _process_local_image(path: str):
    """用 PIL 读取本地图片一次，返回 (格式小写, data_uri, 字节数, 宽, 高)。

    data_uri 形如 ``data:image/<格式>;base64,<编码>``，与接口文档 base64List 要求一致。
    """
    with Image.open(path) as im:
        im.load()
        pil_fmt = (im.format or "").upper()
        save_fmt = "JPEG" if pil_fmt == "JPG" else pil_fmt
        fmt_lower = _PIL_FMT_MAP.get(pil_fmt, pil_fmt.lower())
        w, h = im.size
        buf = io.BytesIO()
        im.save(buf, format=save_fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return fmt_lower, f"data:image/{fmt_lower};base64,{b64}", os.path.getsize(path), w, h


def _check_image_limits(label: str, size_bytes: Any, w: Any, h: Any) -> None:
    """单张参考图：≤10MB 且像素 ≤6000×6000；信息缺失（None）则跳过该项。"""
    if size_bytes is not None and int(size_bytes or 0) > MAX_IMAGE_BYTES:
        raise ValueError(f"{label} 超过单张大小上限 10MB：实际 {size_bytes} 字节")
    if w is not None and h is not None and int(w) * int(h) > MAX_IMAGE_PIXELS:
        raise ValueError(f"{label} 超过单张像素上限 6000x6000：实际 {w}x{h}")


def _validate_file_ids(file_ids: List[str], dispatcher: ApiDispatcher) -> None:
    """batch_get 校验 fileId 存在性 + 单张大小/像素（size/宽高缺失则跳过该项）。"""
    resp = dispatcher.personal_saas.batch_get(BatchGetRequest(file_ids=list(file_ids)))
    raw_results = (((resp.raw or {}).get("data") or {}).get("batchFileResults") or [])
    meta_by_fid: Dict[str, Dict[str, Any]] = {}
    for row in raw_results:
        if not isinstance(row, dict):
            continue
        src = row.get("srcFile") or {}
        fid = str(src.get("fileId") or row.get("fileId") or "").strip()
        mm = src.get("mediaMetaInfo") or {}
        meta_by_fid[fid] = {
            "size": src.get("size"),
            "width": mm.get("width"),
            "height": mm.get("height"),
        }
    for item in resp.batch_file_results:
        fid = str(item.file_id or (item.src_file.file_id if item.src_file else "")).strip()
        if item.src_file is None:
            raise RuntimeError(f"输入的参考图 fileId 不存在或无法访问: {fid}")
        meta = meta_by_fid.get(fid, {})
        _check_image_limits(f"参考图 fileId {fid}", meta.get("size"), meta.get("width"), meta.get("height"))


def _validate_seed(seed: Optional[int]) -> None:
    if seed is None:
        return
    if seed < SEED_MIN or seed > SEED_MAX:
        raise ValueError(f"seed 取值范围为 [{SEED_MIN}, {SEED_MAX}]，实际 {seed}")


def _validate_size(size_str: Optional[str]) -> None:
    if not size_str:
        return
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", size_str)
    if not m:  # 非 WxH（如 2K/3K）不校验，透传给接口
        return
    w, h = int(m.group(1)), int(m.group(2))
    aspect = w / h
    if aspect < ASPECT_MIN or aspect > ASPECT_MAX:
        raise ValueError(f"size 宽高比范围为 [1/16, 16]，{size_str} 的宽高比 {aspect:.4f} 超范围")
    pixels = w * h
    if pixels < SIZE_PIXELS_MIN or pixels > SIZE_PIXELS_MAX:
        raise ValueError(
            f"size 总像素范围约 [{SIZE_PIXELS_MIN}, {SIZE_PIXELS_MAX}]（2560x1440 ~ 3072x3072），"
            f"{size_str} 的总像素 {pixels} 超范围"
        )


def _validate_sequential(ref_count: int, max_images: Optional[int]) -> None:
    if max_images is None:
        return
    if max_images < SEQ_MAX_MIN or max_images > SEQ_MAX_MAX:
        raise ValueError(f"sequentialMaxImages 取值范围为 [{SEQ_MAX_MIN}, {SEQ_MAX_MAX}]，实际 {max_images}")
    if ref_count + max_images > SEQ_TOTAL_MAX:
        raise ValueError(
            f"需满足「参考图数量 + 生成数量 ≤ {SEQ_TOTAL_MAX}」，"
            f"当前参考图 {ref_count} + maxImages {max_images} = {ref_count + max_images}"
        )


# ──────────────────────────── 预览 ────────────────────────────


def build_preview(payload: Dict[str, Any]) -> str:
    endpoint = "/richlifeApp/aiService/api/image/generate"
    send_type = payload.get("sendType")
    if send_type == 2:
        input_desc = f"输入图 base64 ×{len(payload.get('base64List') or [])}"
    elif send_type == 3:
        input_desc = f"输入图 fileId ×{len(payload.get('fileIdList') or [])}"
    elif send_type is None:
        input_desc = "无输入图（文生图）"
    else:
        input_desc = f"sendType={send_type}"

    lines = [
        f"已识别为端内 AI 图片能力请求：AI生图（{'文生图' if send_type is None else '图生图'}）",
        f"接口能力：POST {endpoint}",
        f"输入对象：{input_desc}",
        f"生成提示词：{payload['query']}",
    ]
    if payload.get("size"):
        lines.append(f"生成尺寸：{payload['size']}")
    if payload.get("outputFormat"):
        lines.append(f"输出格式：{payload['outputFormat']}")
    if payload.get("sequentialImageGeneration"):
        lines.append(f"组图模式：{payload['sequentialImageGeneration']}")
    if payload.get("optimizePromptOptions"):
        lines.append(f"提示词优化：{payload['optimizePromptOptions'].get('model')}")
    if payload.get("supplierType") is not None:
        lines.append(f"supplierType：{payload['supplierType']}")
    if "sourceTaskId" in payload:
        lines.append(f"sourceTaskId：{payload['sourceTaskId']}")
    lines.extend([
        "当前仅预览，尚未执行。",
        "请求体：",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "确认执行请添加 `--confirm`。",
    ])
    return "\n".join(lines)


# ──────────────────────────── 主流程 ────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AI生图（主入口）")
    parser.add_argument("--confirm", action="store_true", help="是否确认执行")
    parser.add_argument("--query", required=True, help="生成提示词（用户描述）")

    # 输入图：可不传；不传即为文生图（仅 query）
    parser.add_argument(
        "--file-id", nargs="+", metavar="FILE_ID",
        help="输入图云盘 fileId 列表（sendType=3）；多个空格分隔，至少 1 张",
    )

    # 生成参数
    parser.add_argument("--size", help="生成尺寸，如 2048x2048")
    parser.add_argument("--seed", type=int, default=None, help="随机种子 [-1, 2147483647]，默认不传")
    parser.add_argument(
        "--sequential-image-generation", choices=["auto", "disabled"], default=None,
        help="组图模式：auto 自动判断组图 / disabled 单张",
    )
    parser.add_argument(
        "--sequential-max-images", type=int, default=None,
        help="组图最大张数（仅 sequentialImageGeneration=auto 生效）",
    )
    parser.add_argument(
        "--optimize-prompt-model", choices=["standard", "fast"], default=None,
        help="提示词优化模型：standard / fast",
    )

    # 保存
    parser.add_argument(
        "--save-dir-id", default=None,
        help="另存到指定目录的 fileId；传入后结果将直接移动到该目录并输出去查看回执。"
        "目录解析须由「云盘文件管理」技能完成，本参数只收 fileId",
    )
    parser.add_argument(
        "--no-archive", action="store_true",
        help="跳过归档：不移动结果到保存目录、不输出 filePathList 卡片，仅输出 bigImageList 结果卡"
        "（用于用户明确保存到知识库等场景，结果 fileId 由后续技能直接承接）；"
        "与 --save-dir-id 同传时以 --save-dir-id 为准",
    )
    parser.add_argument("--verbose", action="store_true", help="输出详细信息")
    args = parser.parse_args()

    global _VERBOSE
    _VERBOSE = args.verbose

    clear_api_timings()
    operation_log.init_operation_log(command="ai_image_generate")
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

    dispatcher = ApiDispatcher(host=HOST, auth_fn=get_auth_header)

    # 输入图数量（不传为文生图，n_ref=0）
    # 超过单批上限 MAX_REF_IMAGES 时自动分批（每批 ≤14 张，同 query 逐批提交、统一轮询、汇总输出）
    n_ref = len(args.file_id) if args.file_id else 0
    if n_ref > MAX_REF_IMAGES and (args.sequential_image_generation or args.sequential_max_images):
        raise ValueError(
            f"组图模式不支持分批：输入图超过 {MAX_REF_IMAGES} 张时请勿使用 "
            f"sequentialImageGeneration / sequentialMaxImages（组图本身要求 参考图数+生成数 ≤ {SEQ_TOTAL_MAX}）"
        )

    # ── 1. 判定 sendType + 对应列表 + 输入校验 ──
    # 不传时 send_type 保持 None，即文生图（payload 不带 sendType）
    send_type: Optional[int] = None
    file_id_list: Optional[List[str]] = None

    if args.file_id:
        send_type = 3
        file_id_list = list(args.file_id)
        _validate_file_ids(file_id_list, dispatcher)   # 存在性 + 单张大小/像素（缺失跳过）

    ref_count = len(file_id_list) if file_id_list is not None else 0

    # 标量参数校验：seed / size / 组图
    _validate_seed(args.seed)
    _validate_size(args.size)
    _validate_sequential(ref_count, args.sequential_max_images)

    # ── 2. 嵌套选项 ──
    sequential_options: Optional[Dict[str, Any]] = None
    if args.sequential_image_generation == "auto" and args.sequential_max_images is not None:
        sequential_options = {"maxImages": args.sequential_max_images}
    optimize_options: Optional[Dict[str, Any]] = None
    if args.optimize_prompt_model is not None:
        optimize_options = {"model": args.optimize_prompt_model}

    # ── 3. 构造请求（支持分批：每批 ≤MAX_REF_IMAGES 张，同一 query 逐批提交）──
    if file_id_list is not None:
        batch_inputs = [
            file_id_list[i:i + MAX_REF_IMAGES]
            for i in range(0, len(file_id_list), MAX_REF_IMAGES)
        ]
    else:  # 文生图：无输入图，单批
        batch_inputs = [None]
    n_batches = len(batch_inputs)

    def _build_request(
        fid_list: Optional[List[str]],
        poll_max_attempts: Optional[int] = None,
    ) -> AiImageGenerateRequest:
        kwargs: Dict[str, Any] = dict(
            query=args.query,
            send_type=send_type,
            file_id_list=fid_list,
            size=args.size,
            seed=args.seed,
            sequential_image_generation=args.sequential_image_generation,
            sequential_image_generation_options=sequential_options,
            watermark=WATERMARK,
            optimize_prompt_options=optimize_options,
            supplier_type=SUPPLIER_TYPE,
        )
        if poll_max_attempts is not None:
            kwargs["poll_max_attempts"] = poll_max_attempts
        return AiImageGenerateRequest(**kwargs)

    payload = _build_request(batch_inputs[0]).to_payload()

    _print(build_preview(payload))
    if n_batches > 1:
        print(
            f"输入图共 {ref_count} 张，超过单批上限 {MAX_REF_IMAGES} 张，"
            f"将自动分 {n_batches} 批处理（每批 ≤{MAX_REF_IMAGES} 张，同一提示词逐批提交、统一轮询、汇总输出）。",
            flush=True,
        )
    if not args.confirm:
        return

    _print("开始调用 AI生图 接口...")

    # ── 4. 提交 + 轮询：直接用现有 AiImageGenerateApi（与 ai_retouch 同款）──
    #    return_task_id=True：长任务超时不抛错，返回 status=处理中 + taskId，交由用户用 status.py 兜底。
    api = AiImageGenerateApi(host=HOST, auth_fn=get_auth_header)

    if n_batches > 1:
        _run_batches(api, args, batch_inputs, _build_request, raw_session, dispatcher)
        return

    poll_resp = api.execute(_build_request(batch_inputs[0]), return_task_id=True)

    # taskId 无论成败始终输出，便于用户用 status.py 追踪或排查
    print(f"任务已提交，taskId={poll_resp.task_id}", flush=True)

    # ── 5. 分支处理（结果处理与 ai_retouch 一致）──
    if poll_resp.is_success:
        _handle_success(poll_resp, args, raw_session, dispatcher)
        return

    if poll_resp.status == 2:  # 处理中：~120s 预算用尽，交出 taskId 供用户主动轮询（不自动触发）
        print(
            f"任务仍在生成中（已达默认轮询上限），taskId={poll_resp.task_id}。"
            f"需要查看结果时，可主动运行 status.py --task-id {poll_resp.task_id} --wait 查询。",
            flush=True,
        )
        return

    # status in (4 失败, 5 过期)：透出 taskId 与服务端原始 code/message，便于直接定位失败原因
    raw = poll_resp.raw or {}
    raise RuntimeError(
        f"异步任务未成功完成，status={poll_resp.status}({poll_resp.status_text})，"
        f"taskId={poll_resp.task_id}，code={raw.get('code')}，message={raw.get('message')}"
    )


def _run_batches(api, args, batch_inputs, build_request, raw_session, dispatcher) -> None:
    """多批执行：全部批次快速提交（服务端并行）→ 逐批统一轮询 → 汇总结果一次输出。"""
    n = len(batch_inputs)

    # 提交阶段：每批仅 1 次探测轮询，快速拿到 taskId，让所有批次在服务端并行执行
    submit_resps = []
    for i, fid_list in enumerate(batch_inputs, 1):
        resp = api.execute(build_request(fid_list, poll_max_attempts=1), return_task_id=True)
        print(f"批次 {i}/{n} 已提交，taskId={resp.task_id}", flush=True)
        submit_resps.append(resp)

    # 轮询阶段：逐批轮询到终态（各批次在服务端并行，通常第一批就绪时其余也已就绪）
    success_infos: Dict[str, Dict[str, Any]] = {}
    pending: List[Any] = []  # (批次号, taskId)
    failed: List[Any] = []   # (批次号, 状态描述)
    for i, resp in enumerate(submit_resps, 1):
        r = resp
        if r.status == 2:  # 探测轮询未就绪 → 进入正式轮询（默认 60 次 × 2s ≈ 120s）
            r = api._poll(resp.task_id, build_request(None), return_task_id=True)
        if r.is_success:
            for info in r.file_info_list or []:
                if isinstance(info, dict) and info.get("fileId"):
                    success_infos[info["fileId"]] = info
        elif r.status == 2:
            pending.append((i, r.task_id))
        else:
            failed.append((i, f"status={r.status}({r.status_text})"))

    # 汇总输出：所有成功批次的结果合并为一组卡片
    if success_infos:
        _emit_results(
            list(success_infos.keys()), success_infos, args.save_dir_id,
            raw_session, dispatcher, no_archive=args.no_archive,
        )

    for i, task_id in pending:
        print(
            f"批次 {i}/{n} 仍在生成中（已达轮询上限），taskId={task_id}。"
            f"可运行 status.py --task-id {task_id} --wait 查询（支持一次传多个 task-id）。",
            flush=True,
        )

    if failed:
        msg = "；".join(f"批次 {i} 未成功：{t}" for i, t in failed)
        if not success_infos and not pending:
            raise RuntimeError(f"异步任务未成功完成：{msg}")
        print(f"警告：{msg}", flush=True)


def _handle_success(poll_resp, args, raw_session: str, dispatcher: ApiDispatcher) -> None:
    """终态成功：取结果 fileId → 移动 → 直出渲染卡（与 ai_retouch 一致）。"""
    _print(json.dumps(extract_poll_result(poll_resp), ensure_ascii=False, indent=2))

    result_file_ids: List[str] = []
    result_file_infos: Dict[str, Dict[str, Any]] = {}
    for info in poll_resp.file_info_list or []:
        if isinstance(info, dict) and info.get("fileId"):
            result_file_ids.append(info["fileId"])
            result_file_infos[info["fileId"]] = info

    if result_file_ids:
        _emit_results(
            result_file_ids, result_file_infos, args.save_dir_id,
            raw_session, dispatcher, no_archive=args.no_archive,
        )
    else:
        handle_sub_result_output(poll_resp, OUTPUT_DIR, dispatcher, cli='ai_image_generate')


def _emit_results(
    result_file_ids: List[str],
    result_file_infos: Dict[str, Dict[str, Any]],
    save_dir_id: Optional[str],
    raw_session: str,
    dispatcher: ApiDispatcher,
    no_archive: bool = False,
) -> None:
    """结果 fileId 列表 → 移动到目标目录 → 直出 filePathList + bigImageList 渲染卡。

    未传 save_dir_id 时归档到会话默认目录（/AI空间/<APP>/对话文件 下按会话生成的目录）。
    no_archive=True（且未传 save_dir_id）时跳过归档：不建目录、
    不移动、不出 filePathList 卡，仅输出 bigImageList 结果卡（结果 fileId 供后续技能承接）。
    """
    if save_dir_id:
        target_dir_id = save_dir_id
        target_dir_path = ""
    elif no_archive:
        write_cli_output_line("已跳过归档（--no-archive），结果文件保留在生成位置")
        emit_big_image_list_card(result_file_ids, cli='ai_image_generate')
        return
    else:
        target_dir_id, target_dir_path = ensure_session_default_dir(raw_session)

    dir_id, dir_path, move_result = "", "", None
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
