#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convert 业务：HEIC/LIVP 批量转 JPG，纯本地、不触碰云盘。

云盘文件须先由云盘管理技能下载到本地再传入。输出统一 JPEG
（质量 95、EXIF Orientation 归一），LIVP 解包取静止帧（规则同 edit）。
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from typing import List, Set, Tuple

from PIL import Image, ImageOps

from utils.tools import (
    CONVERT_INPUT_MAX,
    CONVERT_NAME_TS_FORMAT,
    CONVERT_OUTPUT_DIRNAME,
    OUTPUT_DIR,
    ensure_heif_support,
    extract_livp_frame,
    save_edited_image,
    sniff_image_kind,
)


def _parse_and_validate(raw: str) -> List[str]:
    """解析 --input（逗号分隔），整体校验；任一不合格抛错，不转换任何文件。"""
    if not raw or not str(raw).strip():
        raise ValueError("缺少 --input：逗号分隔的本地绝对路径（1-10 个）")
    paths = [p.strip() for p in str(raw).split(',') if p.strip()]
    if not paths:
        raise ValueError("--input 未解析到任何路径")
    if len(paths) > CONVERT_INPUT_MAX:
        raise ValueError(f"一次最多转换 {CONVERT_INPUT_MAX} 个文件，当前 {len(paths)} 个")
    problems: List[str] = []
    for p in paths:
        if not os.path.isabs(p):
            problems.append(f"{p}: 需为绝对路径")
        elif not os.path.isfile(p):
            problems.append(f"{p}: 文件不存在")
        elif sniff_image_kind(p) == 'image':
            problems.append(f"{os.path.basename(p)}: 非 HEIC/LIVP（常见图片无需转换）")
    if problems:
        raise ValueError("输入路径无效：\n" + "\n".join(f"- {x}" for x in problems))
    return paths


def _next_output_name(out_dir: str, used_names: Set[str]) -> str:
    """输出名 image_<YYYYMMDDHHMMSS>.jpg；同名已存在（本批或磁盘）追加序号，不覆盖。"""
    ts = datetime.now().strftime(CONVERT_NAME_TS_FORMAT)
    name = f"image_{ts}.jpg"
    n = 2
    while name in used_names or os.path.exists(os.path.join(out_dir, name)):
        name = f"image_{ts}_{n}.jpg"
        n += 1
    used_names.add(name)
    return name


def _convert_one(src: str, out_dir: str, used_names: Set[str]) -> str:
    """转换单个 HEIC/LIVP 文件，返回输出绝对路径。"""
    frame_path = src
    tmp_dir: str = ""
    if sniff_image_kind(src) == 'livp':
        tmp_dir = tempfile.mkdtemp(prefix='livp_frame_')
        frame_path = extract_livp_frame(src, tmp_dir)
    try:
        if sniff_image_kind(frame_path) == 'heic':
            ensure_heif_support()
        with Image.open(frame_path) as im:
            im.load()
            orig_exif = im.getexif()
            im = ImageOps.exif_transpose(im)  # 物理转正像素，EXIF Orientation 归一写回
            out_path = os.path.join(out_dir, _next_output_name(out_dir, used_names))
            save_edited_image(im, out_path, 'JPEG', exif=orig_exif)
        return out_path
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def run_convert(args: argparse.Namespace) -> None:
    paths = _parse_and_validate(getattr(args, 'input', None))
    out_dir = os.path.join(OUTPUT_DIR, CONVERT_OUTPUT_DIRNAME)
    os.makedirs(out_dir, exist_ok=True)

    used_names: Set[str] = set()
    failures: List[Tuple[str, str]] = []
    for p in paths:
        try:
            out_path = _convert_one(p, out_dir, used_names)
            print(f"已转换：{p} → {out_path}")
        except Exception as exc:  # 单文件失败不中断其余
            print(f"转换失败：{p}（{exc}）")
            failures.append((p, str(exc)))

    print(f"转换完成：成功 {len(paths) - len(failures)} 个，失败 {len(failures)} 个")
    if failures:
        raise SystemExit(1)
