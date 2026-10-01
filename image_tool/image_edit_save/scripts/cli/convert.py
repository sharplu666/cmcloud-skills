#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convert 子命令入口：预检与编排在 services/convert（异常向上抛，由进程退出码承载）。"""

import argparse

from services.convert import run_convert


def run(args: argparse.Namespace) -> None:
    run_convert(args)
