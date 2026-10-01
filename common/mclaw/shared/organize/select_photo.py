#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 选图编排：提交 → 轮询 → good 集过滤回原顺序。

供 refine select（pick）与整理回忆故事（refine_for_memory）的选图引擎切换使用：
把候选 ``File`` 列表交给 ``album.select_photo_submit``（imageIdFile 每行
``{"fileId","score"}``，score 取 ``aiAnalysisInfo.score``，缺失走模型默认 '1.0'），
轮询 ``album.select_photo_result`` 至终态，SUCCESS 时取 ``goodImages`` fileId 集，
**按原输入顺序**返回存活 ``File``。

本模块只抛异常不打日志：回退与告警日志由调用方统一落（避免同一异常双份日志）。
SUCCESS 但 ``goodImages`` 为空不是异常——返回 ``[]``，空结果路径交调用方既有
报错处理（不回退）。
"""

from __future__ import annotations

import time
from typing import List

from mclaw.api import ApiDispatcher
from mclaw.api.album.select_image_api import (
    SELECT_PHOTO_STATUS_SUCCESS,
    SelectPhotoItem,
    SelectPhotoResultRequest,
    SelectPhotoSubmitRequest,
)
from mclaw.api.search_fusion import File


__all__ = [
    'SelectPhotoError',
    'select_photos',
    'SELECT_PHOTO_POLL_INTERVAL_SEC',
    'SELECT_PHOTO_POLL_TIMEOUT_SEC',
]


#: 轮询间隔（秒）
SELECT_PHOTO_POLL_INTERVAL_SEC: float = 5.0
#: 轮询总超时（秒）
SELECT_PHOTO_POLL_TIMEOUT_SEC: float = 180.0


class SelectPhotoError(Exception):
    """AI 选图失败（提交业务失败 / 查询失败 / 终态非成功 / 轮询超时）。"""


def select_photos(
    dispatcher: ApiDispatcher,
    files: List[File],
    *,
    count: int,
    poll_interval_sec: float = SELECT_PHOTO_POLL_INTERVAL_SEC,
    poll_timeout_sec: float = SELECT_PHOTO_POLL_TIMEOUT_SEC,
) -> List[File]:
    """AI 选图并按原输入顺序返回存活的 ``File`` 列表。

    Args:
        dispatcher: 调用方注入的 ``ApiDispatcher``（选图接口经它触网）。
        files: 候选图片（空列表直接返回空）。
        count: 选图数量（refine pick 用 ``--pick``，回忆故事用桶 top-N）。
        poll_interval_sec / poll_timeout_sec: 轮询节奏与总超时。

    Returns:
        ``goodImages`` 命中的 ``File``（原输入顺序）；SUCCESS 但空时为 ``[]``。

    Raises:
        SelectPhotoError: 提交业务失败 / 查询业务失败 / 终态 FAILED·CANCELLED / 超时。
        Exception: 网络等底层异常原样上抛（调用方按选图失败回退处理）。
    """
    if not files:
        return []

    items = []
    for file_ in files:
        ai = getattr(file_, 'ai_analysis_info', None)
        score = getattr(ai, 'score', None) if ai is not None else None
        items.append(SelectPhotoItem(file_id=file_.file_id, score=score))

    submit = dispatcher.album.select_photo_submit(
        SelectPhotoSubmitRequest(items=items, count=int(count))
    )
    if not submit.success or not submit.task_id:
        raise SelectPhotoError(
            f'提交失败 code={submit.code} msg={submit.message!r}'
        )

    deadline = time.monotonic() + poll_timeout_sec
    while True:
        resp = dispatcher.album.select_photo_result(
            SelectPhotoResultRequest(task_id=submit.task_id)
        )
        if not resp.success:
            raise SelectPhotoError(
                f'查询失败 code={resp.code} msg={resp.message!r}'
            )
        if resp.is_terminal:
            if resp.status != SELECT_PHOTO_STATUS_SUCCESS:
                raise SelectPhotoError(
                    f'任务终态非成功 status={resp.status} msg={resp.message!r}'
                )
            good_ids = {
                str(item.get('fileId') or '')
                for item in (resp.good_images or [])
            }
            return [f for f in files if str(f.file_id or '') in good_ids]
        if time.monotonic() >= deadline:
            raise SelectPhotoError(
                f'轮询超时（{poll_timeout_sec}s）taskId={submit.task_id}'
            )
        time.sleep(poll_interval_sec)
