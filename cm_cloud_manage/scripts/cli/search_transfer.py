#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：search-transfer —— 转存查询（分享/圈子/发现转存，纯查询不落盘）。

校验在 ``services/search_transfer/args``，编排在 ``runner``；异常梯与
``cli/dynamic.py`` 同构但**无让出档**（不落盘无断点，纯单页查询）。参数全为
裸字符串，仅 6 个参数（docs/cli_design.md §10.1），其它一律不注册。
"""

from __future__ import annotations

import argparse

from cli.cli_runtime import (
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
)
from services.search.degraded import describe_backend_error
from services.errors import CliValidationError, OperationServiceError
from services.search_transfer.args import validate_search_transfer
from services.search_transfer.runner import run_search_transfer
from services.stdout_receipt import error_meta


def run(args: argparse.Namespace) -> int:
    """search-transfer 入口：校验 → 单页查询；异常梯统一转 record=meta 回执。"""
    command = 'search-transfer'
    try:
        targs = validate_search_transfer(args)
        run_search_transfer(targs)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except OperationServiceError as exc:
        error_meta(command, exc.message)
        return EXIT_BUSINESS_ERROR
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
