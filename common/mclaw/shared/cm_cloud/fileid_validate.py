#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验云盘 fileId 是否存在（基于 batchGet 同步接口）。

复用 ``dispatcher.personal_saas.batch_get``：
  POST /richlifeApp/personalSaas/file/batchGet，单次最多 100 个 fileId，请求即返回。

判定规则（经 ``batch_get_api`` 归一化后）：单个条目 ``src_file is not None`` 即"存在"
（``errCode != '0000'`` 或 ``srcFile`` 残缺时 ``src_file`` 被置 ``None``，如 ``04000010 资源不存在``）。

能力：
  - 超过 100 个 fileId 自动分批；
  - 多批用线程池并发执行；
  - 逐批异常隔离（某批 HTTP 失败 → 该批全部记 ``False``，不向上抛）；
  - 返回与输入**同序、同长**的 ``List[bool]``（``True``=存在），空串/空白/未返回的 id 记 ``False``。

并发模式参考 ``mclaw.shared.organize.selector.image_deduplicator``（共享同一个 dispatcher，
按下标收集结果，逐批异常隔离）。本模块**不发 HTTP、不持鉴权/host**——所有 HTTP 通过
调用方注入的 ``dispatcher: ApiDispatcher`` 完成。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas.batch_get_api import BatchGetRequest

try:
    from cli_timing import write_cli_output_line
except ImportError:
    def write_cli_output_line(line: str) -> None:
        print(line, flush=True)


__all__ = ['check_fileids_exist', 'BATCH_GET_MAX_IDS']

#: batchGet 单次最多 100 个 fileId（接口限制）
BATCH_GET_MAX_IDS = 100

#: 默认线程池并发度
_DEFAULT_MAX_WORKERS = 4


def _chunk(seq: List[str], size: int) -> List[List[str]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def _check_batch(file_ids: List[str], dispatcher: ApiDispatcher) -> Dict[str, bool]:
    """单批（≤100）校验，返回 ``{fileId: exists}``。响应中未出现的 id 不在此 dict 内。"""
    resp = dispatcher.personal_saas.batch_get(BatchGetRequest(file_ids=list(file_ids)))
    out: Dict[str, bool] = {}
    for item in (resp.batch_file_results or []):
        fid = str(item.file_id or '').strip()
        if not fid:
            continue
        # batch_get_api 已归一化：errCode != 0000 或 srcFile 残缺 → src_file=None
        out[fid] = item.src_file is not None
    return out


def check_fileids_exist(
    file_ids: List[str],
    dispatcher: ApiDispatcher,
    *,
    max_workers: int = _DEFAULT_MAX_WORKERS,
) -> List[bool]:
    """批量校验 fileIds 是否存在，返回与输入**同序、同长**的 ``List[bool]``。

    Args:
        file_ids: 待校验 fileId 列表（原样保留顺序与长度；空串/空白记 ``False``）。
        dispatcher: 调用方注入的 ``ApiDispatcher``。
        max_workers: 线程池并发度；``<=1`` 或仅 1 批时串行执行（避免线程开销）。

    Returns:
        ``List[bool]``，长度与顺序与 ``file_ids`` 完全一致；``True`` 表示该 fileId 存在且可访问。
        重复 id 复用同一结果；响应中未返回的 id 记 ``False``。
    """
    raw = [str(x) for x in (file_ids or [])]

    # 去重 + 去空，得到待查集合（保留首次出现顺序，用于分批发送）
    seen: set[str] = set()
    unique_ids: List[str] = []
    for x in raw:
        fid = x.strip()
        if fid and fid not in seen:
            seen.add(fid)
            unique_ids.append(fid)

    if not unique_ids:
        return [False for _ in raw]

    batches = _chunk(unique_ids, BATCH_GET_MAX_IDS)

    def _run_one(batch: List[str]) -> Dict[str, bool]:
        try:
            return _check_batch(batch, dispatcher)
        except Exception as exc:  # 单批降级：该批全部视为不存在，不影响其他批
            write_cli_output_line(
                f'[WARN] batchGet 校验失败，该批 {len(batch)} 个 fileId 视为不存在：{exc}'
            )
            return {fid: False for fid in batch}

    merged: Dict[str, bool] = {}
    if len(batches) == 1 or max_workers <= 1:
        # 串行：1 批或并发关闭，保持简单确定性
        for batch in batches:
            merged.update(_run_one(batch))
    else:
        # 并行：按下标收集，保持与串行一致的合并顺序
        partials: List[Dict[str, bool]] = [{} for _ in batches]
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(batches)))) as pool:
            future_to_idx = {pool.submit(_run_one, b): i for i, b in enumerate(batches)}
            for fut, idx in future_to_idx.items():
                partials[idx] = fut.result()
        for partial in partials:
            merged.update(partial)

    # 按原输入顺序输出；空串/空白/未返回 → False，重复 id 复用同一结果
    return [merged.get(x.strip(), False) if x.strip() else False for x in raw]
