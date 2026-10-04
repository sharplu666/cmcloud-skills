#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：semantic-search —— 语义搜图（--query 一句自然语言，仅 --query/--mode 两参）。

校验在 ``services/search/args``（validate_semantic_search），任务构建与检索编排复用
``services/search``（param_build / fetch_loop）；「异常→回执」映射内聚在本模块
run() 内（与 cli/search.py 同构，入口 main.py 保持纯分发）。参数全为裸字符串，
校验失败走 ``record=meta status=error`` 回执。
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
from services.search.degraded import describe_backend_error
from services.errors import CliValidationError, OperationServiceError
from services.search.args import validate_semantic_search
from services.search.fetch_loop import run_search
from services.search.param_build import build_search_task
from services.search_fetch import FetchYield
from services.stdout_receipt import error_meta, yielded_meta


def run(args: argparse.Namespace) -> int:
    """semantic-search 入口：校验 → 组任务 → 跑检索；异常梯统一转 record=meta 回执。

    ``OperationServiceError`` 是 ``RuntimeError`` 子类，必须先于 RuntimeError 捕获；
    ``FetchYield`` 不继承 RuntimeError，独立成档（让出 ≠ 失败）。
    """
    command = 'semantic-search'
    try:
        task = build_search_task(validate_semantic_search(args))
        run_search(task)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except OperationServiceError as exc:
        error_meta(command, exc.message)
        return EXIT_BUSINESS_ERROR
    except FetchYield as exc:
        # 让出 ≠ 失败：断点已落盘，原样重跑同一命令（next.rerun）即从断点续拉。
        # 语义模式无动态时间窗，重跑保持参数一字不改即可。
        total_part = f'/{exc.total}' if exc.total else ''
        yielded_meta(
            command,
            say_to_user=(
                f'照片较多，已读取 {exc.fetched}{total_part} 张，正在自动继续～'
                '不想等的话，直接说「就按已读取的整理」～'
            ),
            rerun_cmd='python3 main.py ' + ' '.join(sys.argv[1:]),
        )
        return EXIT_SEARCH_YIELDED
    except RuntimeError as exc:
        _backend_hint = describe_backend_error(exc)
        if _backend_hint:
            error_meta(command, _backend_hint, code='BACKEND_DOWN', retryable=False)
        else:
            error_meta(command, f'服务端错误：{exc}；请停止并交用户决策，勿自动重试')
        return EXIT_BUSINESS_ERROR
    except Exception as exc:  # noqa: BLE001 兜底：任何未知异常都要给出可行动回执
        error_meta(command, f'内部错误：{type(exc).__name__}: {exc}；请停止并交用户决策')
        return EXIT_INTERNAL_ERROR
    return EXIT_OK
