#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：person-search —— 图文搜人（--file-ids 首搜两跳 / --select-faces 二次单跳）。

校验在 ``services/person_search/args``，编排与检索管线复用 ``services/search``
（fetch_loop / results_store / stdout_receipt）；「异常→回执」映射内聚在本模块
run() 内（与 cli/search.py 同构，入口 main.py 保持纯分发）。参数全为裸字符串。
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
from mclaw.shared.organize.search_fetch_store import (
    EXIT_SEARCH_YIELDED,
    SearchFetchYield,
)
from services.search.degraded import describe_backend_error
from services.errors import CliValidationError, OperationServiceError
from services.person_search.args import validate_person_search
from services.person_search.flow import PersonAmbiguityStop, run_person_search
from services.person_search.recognize import PersonNoTargetStop
from services.search.stdout_receipt import emit_search_results
from services.stdout_receipt import error_meta, yielded_meta
from utils.config import PERSON_NO_TARGET_TIPS_PREFIX


def run(args: argparse.Namespace) -> int:
    """person-search 入口：校验 → 编排 → 检索管线；异常梯统一转 record=meta 回执。

    ``PersonAmbiguityStop`` / ``PersonNoTargetStop`` 先于 OperationServiceError/Exception
    捕获：歧义终态（meta + selectFaceList 卡已输出）与未检出目标人脸（业务码
    10000041 / 空壳）均按成功收束——后者发零命中 searchResults 回执（对齐语义搜图
    命中 0，非 error），不落盘不产 handle。
    """
    command = 'person-search'
    try:
        pargs = validate_person_search(args)
        run_person_search(pargs)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except PersonAmbiguityStop:
        # 歧义 = 交互中间态：等待用户选脸后带 --select-faces 二次搜索（提示层协议）
        return EXIT_OK
    except PersonNoTargetStop:
        # 未检出目标人脸 = 正常零命中（对齐语义搜图命中 0）：回执自带 sayToUser
        # （换清晰参考图建议）与 tips（友好提示前置 + 勿自动重搜），不产 error / failedApi
        emit_search_results(
            search_kind='semantic-person', query=pargs.query, file_count=0,
            tips_prefix=PERSON_NO_TARGET_TIPS_PREFIX,
        )
        return EXIT_OK
    except OperationServiceError as exc:
        error_meta(command, exc.message)
        return EXIT_BUSINESS_ERROR
    except SearchFetchYield as exc:
        # 让出 ≠ 失败：断点已落盘，原样重跑同一命令（next.rerun）即从断点续拉。
        # person 参数无动态时间窗，重跑保持参数一字不改即可。
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
