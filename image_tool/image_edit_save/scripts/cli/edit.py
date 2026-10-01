#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit 子命令入口：校验与编排在 services/edit（异常向上抛，由进程退出码承载）。"""

import argparse

from services.edit import run_edit


def run(args: argparse.Namespace) -> None:
    run_edit(args)
