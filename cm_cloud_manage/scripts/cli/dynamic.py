#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：dynamic —— 个人动态搜索（时间窗内查看/上传过的动态）。

校验在 ``services/search/args``，任务构建与检索编排在 ``services/search``；
「异常→回执」映射内聚在本模块 run() 内（与 cli/refine.py 同构；入口 main.py
保持纯分发）。参数全为裸字符串，校验失败走 ``record=meta status=error`` 回执。
"""
from __future__ import annotations

import argparse
import sys

from cli.cli_runtime import (
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
)
from mclaw.shared.organize.search_fetch_store import EXIT_SEARCH_YIELDED
from services.errors import CliValidationError, OperationServiceError
from services.search.args import validate_dynamic
from services.search.fetch_loop import run_search
from services.search.param_build import build_dynamic_task
from services.search_fetch import FetchYield
from services.stdout_receipt import error_meta, yielded_meta


def run(args: argparse.Namespace) -> int:
    """dynamic 入口：校验 → 组任务 → 跑检索；异常梯统一转 record=meta 回执。

    ``OperationServiceError`` 是 ``RuntimeError`` 子类（``SearchServiceError``
    又是其子类），必须先于 RuntimeError 捕获；``FetchYield`` 不继承
    RuntimeError，独立成档（让出 ≠ 失败）。
    """
    command = 'dynamic'
    try:
        task = build_dynamic_task(validate_dynamic(args))
        run_search(task)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except OperationServiceError as exc:
        error_meta(command, exc.message)
        return EXIT_BUSINESS_ERROR
    except FetchYield as exc:
        # 让出 ≠ 失败：断点已落盘，原样重跑同一命令（next.rerun）即从断点续拉。
        # 动态时间窗场景重跑必须保持本次传入的绝对值不变（--end-at 缺省=实时取
        # 当前时间，naive 重跑会令指纹漂移、断点失配）——该固化纪律 next.rerun
        # 表达不了，进 data.tips（模型向；FetchYield 不带时间窗字段，取任务固化
        # 值 task.dynamic_window——task 在 try 首行已组好，此分支必在作用域）。
        # total 为冻结展示值；计数只进自然语言。
        total_part = f'/{exc.total}' if exc.total else ''
        start_at, end_at = task.dynamic_window or (None, None)
        window_tips = (
            '搜索让出：进度已落盘。重跑时时间窗必须保持本次传入的绝对值不变，'
            '其余参数一字不改，即可从断点续拉。'
            if start_at and end_at
            else None
        )
        yielded_meta(
            command,
            say_to_user=(
                f'照片较多，已读取 {exc.fetched}{total_part} 张，正在自动继续～'
                f'不想等的话，直接说「就按已读取的整理」～'
            ),
            rerun_cmd='python3 main.py ' + ' '.join(sys.argv[1:]),
            data={'tips': window_tips} if window_tips else None,
        )
        return EXIT_SEARCH_YIELDED
    except RuntimeError as exc:
        error_meta(command, f'服务端错误：{exc}；请停止并交用户决策，勿自动重试')
        return EXIT_BUSINESS_ERROR
    except Exception as exc:  # noqa: BLE001 兜底：任何未知异常都要给出可行动回执
        error_meta(command, f'内部错误：{type(exc).__name__}: {exc}；请停止并交用户决策')
        return EXIT_INTERNAL_ERROR
    return EXIT_OK
