#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨命令工具函数与常量：格式嗅探、HEIF 支持、livp 解包、图像保存、哈希。"""

import hashlib
import os
import zipfile
from datetime import datetime
from typing import Any, Dict, Optional

from PIL import ImageFile

# 容忍尾部轻微截断的图片（下载不完整时 PIL 默认严格解码会 OSError）
ImageFile.LOAD_TRUNCATED_IMAGES = True

OUTPUT_DIR = os.getenv("TEMP_OUTPUT_DIR", "/home/node/.openclaw/workspace/")

# CLI 名，卡片 meta 文案按此名在 CARD_META_BY_CLI 查表
CLI_NAME = 'image_edit_save'

# 结果文件命名时间戳格式（沿用原 openclaw_image_save 规则）
NAME_TS_FORMAT = '%Y%m%d_%H%M%S'

_DOWNLOAD_TIMEOUT = 120
_UPLOAD_TIMEOUT = 300

# convert 子命令：单次最多输入文件数、输出目录名与命名时间戳格式
CONVERT_INPUT_MAX = 10
CONVERT_OUTPUT_DIRNAME = 'imageConvertJpg'
CONVERT_NAME_TS_FORMAT = '%Y%m%d%H%M%S'


def save_edited_image(
    img: "Image.Image",
    out_path: str,
    src_format: Optional[str],
    exif: "Optional[Image.Exif]" = None,
) -> None:
    """按原格式保存；JPEG 质量 95，非 RGB/L 模式先转 RGB（与日志中 PIL 处理一致）。

    ``exif`` 为原图 EXIF（像素已按 EXIF 物理转正后传入）：写回时将
    Orientation 归一化为 1、宽/高同步为输出尺寸，避免查看器二次旋转，
    其余拍摄信息（Make/Model/DateTime/ExifIFD 等）全部保留。
    """
    fmt = (src_format or 'PNG').upper()
    if fmt == 'JPG':
        fmt = 'JPEG'
    if fmt not in ('JPEG', 'PNG', 'WEBP', 'BMP', 'TIFF', 'GIF'):
        fmt = 'PNG'
    if fmt == 'JPEG' and img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    kwargs: Dict[str, Any] = {'quality': 95} if fmt == 'JPEG' else {}
    if exif:
        try:
            exif[0x0112] = 1  # Orientation → 1：像素已转正
            exif[0x0100] = img.size[0]  # ImageWidth
            exif[0x0101] = img.size[1]  # ImageLength
            kwargs['exif'] = exif.tobytes()
        except Exception:
            kwargs.pop('exif', None)
    img.save(out_path, format=fmt, **kwargs)


# ──────────────────────────── HEIC / LIVP 输入支持 ────────────────────────────

# HEIF 容器的 ftyp brand（heic/heix=HEVC 静图；hevc/hevm/hevs=序列；mif1/msf1=通用 HEIF）
_HEIF_BRANDS = {b'heic', b'heix', b'heim', b'heis', b'hevc', b'hevm', b'hevs', b'mif1', b'msf1'}

# livp 解包可接受的静止帧扩展名（zip 内条目按扩展名筛图，MOV 等不落地）
_LIVP_FRAME_EXTS = ('.heic', '.heif', '.jpg', '.jpeg', '.png')


def sniff_image_kind(path: str) -> str:
    """按魔数识别输入图类型：``heic`` / ``livp``（zip 封装）/ ``image``（其他 PIL 可解码图）。

    不信任扩展名：云盘/本地文件均以内容前 12 字节判定。
    """
    with open(path, 'rb') as f:
        head = f.read(12)
    if head[4:8] == b'ftyp' and head[8:12].lower() in _HEIF_BRANDS:
        return 'heic'
    if head[:2] == b'PK':
        return 'livp'
    return 'image'


def ensure_heif_support() -> None:
    """HEIC 解码依赖检查：缺 pillow-heif 时抛错并附安装命令。

    zipfile 为 Python 标准库、必然存在，无需运行时检查。
    """
    try:
        import pillow_heif
    except ImportError as exc:
        raise RuntimeError(
            "缺少依赖 pillow-heif（HEIC/LIVP 解码必需），请先安装：pip3 install pillow-heif"
        ) from exc
    pillow_heif.register_heif_opener()


def extract_livp_frame(livp_path: str, work_dir: str) -> str:
    """解包 livp（zip：静止帧 + MOV），取静止帧写到 work_dir，返回其本地路径。

    只落地图条目（.heic/.jpg 等），MOV 等其余条目不写出；条目名只取
    basename 再拼接目标路径，规避 zip 路径遍历（Zip Slip）。
    """
    with zipfile.ZipFile(livp_path) as zf:
        img_entries = [n for n in zf.namelist() if n.lower().endswith(_LIVP_FRAME_EXTS)]
        if not img_entries:
            raise ValueError(
                f"livp 解包后未找到图片条目，疑似非实况照片文件: {os.path.basename(livp_path)}"
            )
        entry = img_entries[0]
        os.makedirs(work_dir, exist_ok=True)
        frame_path = os.path.join(work_dir, os.path.basename(entry) or 'frame.heic')
        with open(frame_path, 'wb') as f:
            f.write(zf.read(entry))
    return frame_path


def sha256_file(path: str) -> str:
    """流式计算文件 SHA-256（上传 complete 校验用）。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()
