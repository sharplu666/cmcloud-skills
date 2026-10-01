#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数定义集中地：build_parser 组装 edit / convert 两个子命令。"""

import argparse

from utils.tools import CONVERT_INPUT_MAX


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='main.py',
        description="图片编辑保存（edit：裁剪/旋转/翻转后存云盘；convert：HEIC/LIVP 转 JPG）",
    )
    sub = parser.add_subparsers(dest='command', metavar='<command>')

    # ── edit：原单命令能力，参数面与语义不变 ──
    edit_p = sub.add_parser('edit', help='裁剪/旋转/翻转后保存云盘（纯工具操作）')
    edit_p.add_argument("--confirm", action="store_true", help="是否确认执行（不加仅预览）")

    # 输入图：二选一必填
    img_group = edit_p.add_mutually_exclusive_group(required=True)
    img_group.add_argument("--file-id", metavar="FILE_ID", help="输入图云盘 fileId")
    img_group.add_argument("--image-path", metavar="PATH", help="输入图本地路径")

    # 编辑操作：至少一项（在 services/edit.run_edit 中校验，保证错误文案统一）
    edit_p.add_argument("--rotate", type=float, default=None,
                        help="顺时针旋转角度，如 90 / 180 / 270")
    edit_p.add_argument("--flip", choices=["horizontal", "vertical"], default=None,
                        help="翻转：horizontal 左右镜像 / vertical 上下翻转")
    edit_p.add_argument("--crop-ratio", default=None,
                        help="居中裁剪到目标宽高比，如 3:2、16:9")

    # 保存
    edit_p.add_argument(
        "--save-dir-id", default=None,
        help="另存到指定目录的 fileId；目录解析须由「云盘文件管理」技能完成，本参数只收 fileId。"
        "未传时保存到会话默认文件夹",
    )
    edit_p.add_argument("--verbose", action="store_true", help="输出详细信息")

    # ── convert：HEIC/LIVP 批量转 JPG（纯本地）──
    convert_p = sub.add_parser('convert', help=f'HEIC/LIVP 批量转 JPG（纯本地，最多 {CONVERT_INPUT_MAX} 个）')
    convert_p.add_argument(
        "--input", required=True, metavar="PATHS",
        help=f"逗号分隔的本地绝对路径（1-{CONVERT_INPUT_MAX} 个）；云盘文件需先下载到本地",
    )

    return parser
