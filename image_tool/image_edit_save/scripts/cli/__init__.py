# -*- coding: utf-8 -*-
"""cli 包：parser.py 集中定义参数；edit.py / convert.py 为子命令入口。"""

from cli.convert import run as run_convert
from cli.edit import run as run_edit
from cli.parser import build_parser

__all__ = ['build_parser', 'run_edit', 'run_convert']
