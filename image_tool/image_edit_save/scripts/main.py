#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
图片编辑保存（主入口）：纯分发，不含业务逻辑与参数定义

子命令：
  edit     原单命令能力（本地裁剪/旋转/翻转 → 上传云盘 → 归档 → 直出渲染卡）
  convert  HEIC/LIVP 批量转 JPG（纯本地，不触碰云盘）

调用方式（云盘 fileId）：
python3 main.py edit --file-id "<云盘fileId>" --rotate 90 --crop-ratio 3:2 --confirm

调用方式（本地图片）：
python3 main.py edit --image-path "<本地图>" --rotate 90 --save-dir-id "<目录fileId>" --confirm

调用方式（HEIC/LIVP 转 JPG，最多 10 个本地绝对路径）：
python3 main.py convert --input "<绝对路径1>,<绝对路径2>"

edit 不加 --confirm 仅打印处理计划预览，不执行（预览阶段不触碰云盘，无需鉴权）。
edit 结果文件命名（沿用原 openclaw_image_save 规则）：
  仅裁剪        → crop_<原文件名>_<时间戳>.<原扩展名>
  仅旋转/翻转   → rotate_<原文件名>_<时间戳>.<原扩展名>
  裁剪+旋转/翻转 → edit_<原文件名>_<时间戳>.<原扩展名>
时间戳格式 YYYYMMDD_HHmmss；同名冲突由服务端 fileRenameMode=force_rename 处理。
convert 输出 <工作目录>/imageConvertJpg/image_<YYYYMMDDHHMMSS>.jpg。
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
# common_auth 位于 skills/common_auth/，scripts 位于 skills/image_tool/image_edit_save/scripts/
# 需回溯 3 层到 skills/
_AUTH_ROOT = os.path.join(_SCRIPT_DIR, "..", "..", "..", "common_auth")
if _AUTH_ROOT not in sys.path:
    sys.path.insert(0, _AUTH_ROOT)
# 让 mclaw 包可 import（skills/common/ 为 sys.path 根）
_MCLAW_ROOT = os.path.join(_SCRIPT_DIR, "..", "..", "..", "common")
if _MCLAW_ROOT not in sys.path:
    sys.path.insert(0, _MCLAW_ROOT)

from cli import build_parser, run_convert, run_edit
from cli_timing import (
    clear_api_timings,
    flush_cli_output_buffer,
    start_cli_output_buffer,
)
from mclaw.shared.cm_cloud.mclaw_jsonl import persist_flushed_stdout
from utils.tools import CLI_NAME

import operation_log

COMMAND_HANDLERS = {
    'edit': run_edit,
    'convert': run_convert,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, 'command', None):
        parser.print_help()
        sys.exit(0)

    clear_api_timings()
    operation_log.init_operation_log(command=CLI_NAME)
    start_cli_output_buffer()

    try:
        COMMAND_HANDLERS[args.command](args)
    finally:
        persist_flushed_stdout(
            flush_cli_output_buffer(
                log_path=operation_log.get_operation_log_path_for_output(),
                log_path_position="end",
            )
        )


if __name__ == "__main__":
    main()
