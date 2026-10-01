#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：play_media —— 按 fileId 播放单条视频/音频。

校验逻辑（PlayMediaTask / --content-type 枚举 / fileId 单值）自 cm_cloud_manage
的 cli/validators 相关段内联迁入（本技能无 validators 模块）；「异常→回执」映射内聚
在本模块 run() 内（与 cli/refine.py / cli/organize.py 同构；无 FetchYield 档——
play_media 不做全量拉取，不产让出）。--content-type 交裸字符串，校验失败走
``record=meta status=error`` 回执而非 argparse usage。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import List

from cli.cli_runtime import (
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_INTERNAL_ERROR,
    EXIT_OK,
    List,
    validate_cloud_file_ids,
)
from cli_timing import write_cli_output_line
from mclaw.shared.cm_cloud.card import Card
from services.atomic.play_media import build_play_media_entry
from services.errors import CliValidationError, OperationServiceError
from services.stdout_receipt import error_meta, ok_meta

#: play_media --content-type 合法值（英文 token；后端 contentType 数字 2/3 是内部映射，不暴露 CLI）
_PLAY_CONTENT_TYPES = ('audio', 'video')

# 英文 content_type → 中文标签（回执文案）
_LABEL = {'audio': '音频', 'video': '视频'}


@dataclass(frozen=True)
class PlayMediaTask:
    """play_media：按 fileId 播放单条视频/音频。"""

    file_id: str
    content_type: str            # 英文 token：'audio' / 'video'（后端 contentType 2/3 下放映射，不暴露 CLI）


def _csv_tokens(raw: str) -> List[str]:
    """空白与逗号混合拆分（兼容 ``id1 id2,id3``），去空项并去重保序。"""
    tokens = [
        part.strip()
        for chunk in str(raw or '').split()
        for part in chunk.split(',')
    ]
    return list(dict.fromkeys(t for t in tokens if t))


def _validate_file_ids(raw: str, *, limit: int, label: str) -> List[str]:
    """fileId CSV → 公共库校验（去重 + 长度）+ 批量上限判定。"""
    tokens = _csv_tokens(raw)
    if not tokens:
        raise CliValidationError(
            f'参数错误：{label} 的 fileId 列表为空；请用逗号或空格分隔多个 fileId'
            '（须来自 CLI 回执或搜索结果，禁止编造）。'
        )
    try:
        ids = validate_cloud_file_ids(tokens, context=label)
    except ValueError as exc:
        raise CliValidationError(str(exc)) from exc
    if len(ids) > limit:
        raise CliValidationError(
            f'参数错误：{label} 最多支持 {limit} 个 fileId（当前 {len(ids)} 个）；'
            '请分批处理，或改用 organize 整理流程。'
        )
    return ids


def validate_play_media(ns: argparse.Namespace) -> PlayMediaTask:
    """play_media：fileId 单值 + --content-type(audio|video)；类型与 batch_get category 交叉校验在 service。"""
    content_type = str(getattr(ns, 'content_type', '') or '').strip().lower()
    if not content_type:
        raise CliValidationError(
            '参数错误：play_media 需要 --content-type（audio=音频 / video=视频）。'
        )
    if content_type not in _PLAY_CONTENT_TYPES:
        raise CliValidationError(
            f'参数错误：--content-type 仅支持 audio（音频）/video（视频），当前传的是'
            f' {getattr(ns, "content_type", "")!r}。'
        )
    file_ids = _validate_file_ids(
        str(getattr(ns, 'file_id', '') or '').strip(), limit=1, label='play_media'
    )
    return PlayMediaTask(file_id=file_ids[0], content_type=content_type)


def run(args: argparse.Namespace) -> int:
    """play_media 入口：校验 → 取播放条目 → ok_meta + 播放卡；异常梯统一转 record=meta 回执。

    ``OperationServiceError`` 是 ``RuntimeError`` 子类，必须先于 RuntimeError 捕获。
    """
    command = 'play_media'
    try:
        task = validate_play_media(args)
        entry = build_play_media_entry(task.file_id, task.content_type)
        label = _LABEL[task.content_type]
        ok_meta(
            'play_media',
            say_to_user=f'已为您播放{label}',
            data={'fileId': task.file_id, 'category': task.content_type},
        )
        card_name = f'{task.content_type}List'
        header = {'loadMore': 'false', 'total': 1, 'searchParam': None}
        for line in Card(
            card_name, [entry], header=header, cli='play_media', count=1,
            result_type='search', summary=f'已为您播放{label}',
        ).generate():
            write_cli_output_line(line)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except OperationServiceError as exc:
        error_meta(command, exc.message)
        return EXIT_BUSINESS_ERROR
    except RuntimeError as exc:
        error_meta(command, f'服务端错误：{exc}；请停止并交用户决策，勿自动重试')
        return EXIT_BUSINESS_ERROR
    except Exception as exc:  # noqa: BLE001 兜底：任何未知异常都要给出可行动回执
        error_meta(command, f'内部错误：{type(exc).__name__}: {exc}；请停止并交用户决策')
        return EXIT_INTERNAL_ERROR
    return EXIT_OK
