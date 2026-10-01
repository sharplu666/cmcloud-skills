#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit 业务：本地裁剪/旋转/翻转 → 上传云盘 → 归档 → 直出渲染卡。

原单命令版逻辑原样迁移（校验顺序、报错文案、输出契约不变）。
"""

import argparse
import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

from PIL import Image, ImageOps

from mclaw.api import ApiDispatcher
from mclaw.api.auth import get_auth_header, get_skill_auth
from mclaw.shared.image_tools import (
    emit_big_image_list_card,
    emit_file_path_list_card,
    ensure_session_default_dir,
    move_result_to_directory,
    resolve_session_from_env,
)
from cli_timing import write_cli_output_line

from services.cloud_io import download_cloud_file, upload_local_file
from utils.tools import (
    CLI_NAME,
    NAME_TS_FORMAT,
    OUTPUT_DIR,
    ensure_heif_support,
    extract_livp_frame,
    save_edited_image,
    sniff_image_kind,
)

_VERBOSE = False


def _print(*args, **kwargs) -> None:
    if _VERBOSE:
        print(*args, **kwargs)


# ──────────────────────────── 纯函数：参数解析 / 图像处理 / 命名 ────────────────────────────


def parse_crop_ratio(text: str) -> Tuple[int, int]:
    """解析目标宽高比，支持 ``3:2`` / ``3：2`` / ``3x2``，返回 (宽, 高)。"""
    m = re.match(r"^\s*(\d+)\s*[:：xX]\s*(\d+)\s*$", str(text or ""))
    if not m:
        raise ValueError(f"裁剪比例格式错误：{text!r}，应为 W:H（如 3:2、16:9）")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise ValueError(f"裁剪比例必须为正数：{text!r}")
    return w, h


def normalize_rotate_degrees(degrees: float) -> float:
    """旋转角度归一化到 (0, 360)；0/360 等效无旋转，返回 0 由调用方忽略。"""
    deg = float(degrees) % 360
    return deg


def apply_edits(
    img: "Image.Image",
    *,
    rotate: Optional[float] = None,
    flip: Optional[str] = None,
    crop_ratio: Optional[Tuple[int, int]] = None,
) -> "Image.Image":
    """按用户指令习惯顺序处理：先旋转，再翻转，最后按比例居中裁剪。

    - rotate：顺时针角度（PIL ``rotate`` 正角为逆时针，故取负），``expand=True``
    - flip：``horizontal`` 左右镜像 / ``vertical`` 上下翻转
    - crop_ratio：(宽, 高) 目标比例，居中裁剪，保留最大面积；比例已一致时不裁
    """
    out = img
    if rotate:
        deg = normalize_rotate_degrees(rotate)
        if deg:
            out = out.rotate(-deg, expand=True)
    if flip == 'horizontal':
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    elif flip == 'vertical':
        out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if crop_ratio:
        rw, rh = crop_ratio
        w, h = out.size
        target = rw / rh
        current = w / h
        if abs(current - target) > 1e-9:
            if current > target:  # 太宽：按高度裁宽度
                new_w = int(h * target)
                left = (w - new_w) // 2
                out = out.crop((left, 0, left + new_w, h))
            else:  # 太高：按宽度裁高度
                new_h = int(w / target)
                top = (h - new_h) // 2
                out = out.crop((0, top, w, top + new_h))
    return out


def edit_prefix(rotate: Optional[float], flip: Optional[str], crop_ratio: Optional[Tuple[int, int]]) -> str:
    """结果文件名前缀：仅裁剪 crop_；仅旋转/翻转 rotate_；组合 edit_。"""
    has_crop = crop_ratio is not None
    has_turn = bool(rotate and normalize_rotate_degrees(rotate)) or bool(flip)
    if has_crop and has_turn:
        return 'edit'
    if has_crop:
        return 'crop'
    return 'rotate'


def build_result_name(src_name: str, prefix: str, ts: Optional[str] = None, ext: Optional[str] = None) -> str:
    """``{prefix}_{原文件名stem}_{时间戳}{扩展名}``；无扩展名补 .png。

    ``ext`` 强制指定输出扩展名（HEIC/LIVP 输入时传 ``.jpg``）。
    """
    stem, src_ext = os.path.splitext(os.path.basename(src_name or 'image'))
    if ext:
        out_ext = ext if ext.startswith('.') else f'.{ext}'
    elif src_ext:
        out_ext = src_ext
    else:
        out_ext = '.png'
    return f"{prefix}_{stem}_{ts or datetime.now().strftime(NAME_TS_FORMAT)}{out_ext}"


# ──────────────────────────── 预览 ────────────────────────────


def build_preview(args: argparse.Namespace) -> str:
    ops: List[str] = []
    if args.rotate is not None and normalize_rotate_degrees(args.rotate):
        ops.append(f"顺时针旋转 {args.rotate:g}°")
    if args.flip:
        ops.append('左右镜像' if args.flip == 'horizontal' else '上下翻转')
    if args.crop_ratio:
        ops.append(f"居中裁剪为 {args.crop_ratio} 比例")
    lines = [
        "已识别为图片编辑保存请求（纯工具操作，不经 AI 模型）",
        f"输入对象：{'云盘图片 1 张（fileId）' if args.file_id else f'本地图片 {args.image_path}'}",
        f"编辑操作：{'；'.join(ops)}",
        f"保存路径：{args.save_dir_id or '默认文件夹'}",
        "当前仅预览，尚未执行。",
        "确认执行请添加 `--confirm`。",
    ]
    return "\n".join(lines)


# ──────────────────────────── 主流程 ────────────────────────────


def run_edit(args: argparse.Namespace) -> None:
    global _VERBOSE
    _VERBOSE = bool(getattr(args, 'verbose', False))

    has_rotate = args.rotate is not None and bool(normalize_rotate_degrees(args.rotate))
    if not has_rotate and not args.flip and not args.crop_ratio:
        raise ValueError("需至少指定一种编辑操作：--rotate / --flip / --crop-ratio")

    # crop 比例提前解析（预览也要校验格式）
    crop_ratio = parse_crop_ratio(args.crop_ratio) if args.crop_ratio else None

    # 预览：不触碰云盘、不需要会话与鉴权
    if not args.confirm:
        print(build_preview(args), flush=True)
        return

    raw_session, session_id = resolve_session_from_env(required=True, error_cls=ValueError)
    _print(f"current session_id={session_id}")

    auth_cfg = get_skill_auth()
    dispatcher = ApiDispatcher(host=auth_cfg.host, auth_fn=get_auth_header)

    # ── 1. 取源图 ──
    if args.file_id:
        src_path, src_name = download_cloud_file(dispatcher, args.file_id, OUTPUT_DIR)
        write_cli_output_line(f"源图已下载: {src_name or args.file_id}")
    else:
        if not os.path.isfile(args.image_path):
            raise FileNotFoundError(f"输入图本地路径不存在: {args.image_path}")
        src_path, src_name = args.image_path, os.path.basename(args.image_path)

    # ── 2. 本地编辑（PIL，先按 EXIF 转正到视觉方向）──
    # LIVP（zip 封装的实况照片）先解包取静止帧；HEIC 帧需 pillow-heif 解码；
    # HEIC/LIVP 输入的结果统一输出 JPEG（原格式写回暂不可靠，见 docs 调研）
    src_kind = sniff_image_kind(src_path)
    frame_path = src_path
    if src_kind == 'livp':
        frame_path = extract_livp_frame(src_path, OUTPUT_DIR)
        if sniff_image_kind(frame_path) == 'heic':
            ensure_heif_support()
    elif src_kind == 'heic':
        ensure_heif_support()

    with Image.open(frame_path) as im:
        im.load()
        src_format = im.format
        orig_exif = im.getexif()
        im = ImageOps.exif_transpose(im)  # 物理转正像素：旋转/裁剪基准与用户视觉一致
        src_size = im.size
        edited = apply_edits(im, rotate=args.rotate, flip=args.flip, crop_ratio=crop_ratio)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_ext = '.jpg' if src_kind in ('heic', 'livp') else None
    result_name = build_result_name(
        src_name, edit_prefix(args.rotate, args.flip, crop_ratio), ext=out_ext
    )
    out_path = os.path.join(OUTPUT_DIR, result_name)
    save_edited_image(edited, out_path, 'JPEG' if out_ext else src_format, exif=orig_exif)
    write_cli_output_line(
        f"本地处理完成: {result_name}（{src_size[0]}x{src_size[1]} → {edited.size[0]}x{edited.size[1]}）"
    )

    # ── 3. 上传到会话默认保存目录 ──
    default_dir_id, default_dir_path = ensure_session_default_dir(raw_session)
    if not default_dir_id:
        raise RuntimeError("创建默认保存目录失败，无法上传结果文件")
    new_file_id, final_name = upload_local_file(dispatcher, out_path, default_dir_id, verbose=_VERBOSE)
    write_cli_output_line(f"上传完成: {final_name}")

    # ── 4. 归档：--save-dir-id 时移动到指定目录（与 ai_image_generate 输出一致）──
    dir_id, dir_path = default_dir_id, default_dir_path
    if args.save_dir_id:
        write_cli_output_line(f"移动结果文件到 {args.save_dir_id} ...")
        move_result = move_result_to_directory([new_file_id], args.save_dir_id, dispatcher)
        write_cli_output_line(f"移动完成: {move_result['message']}")
        dir_id = move_result.get("targetDirFileId") or args.save_dir_id
        dir_path = move_result.get("targetPath") or ""

    # ── 5. 直出渲染卡（与 ai_image_generate 一致：filePathList → bigImageList）──
    if dir_id:
        emit_file_path_list_card(dir_path, dir_id, cli=CLI_NAME)
    emit_big_image_list_card([new_file_id], cli=CLI_NAME)
