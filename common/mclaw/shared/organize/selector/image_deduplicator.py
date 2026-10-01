#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""相似图去重（选图原子能力）。

对一组个人云图片执行相似图去重：每个重复分组只保留图片质量评分最高的一张，
最终返回去重后的文件 ID 列表（保持接口返回顺序）。

**批量优先、同步回退（二选一）**：``deduplicate`` 先走异步批量去重（整单一个
任务，无单次 1000 上限），轮询到已完成后取 result 响应自带的 ``result_file_ids``
（API 层已完成态自动内存下载解析 EOS zip → txt）与入参求交集得到保留集；批量
链路任何异常/畸形（业务失败、失败/过期态、轮询超时、结果文件下载/解析失败即
``result_file_ids`` 为 None、filesNumber 不符、交集为空）一律回退到既有同步分批
链路。批量任务纯分析无服务端副作用，回退重跑同步无重复执行风险。

本模块为**原子能力**：输入所有 fileIds → 输出去重后 fileIds；不涉及桶维度去重
（桶 × N 属上层 ``quality_selector`` 选图）。底层 HTTP 调用经联邦 dispatcher
``api_client.album.image_deduplicate(req)`` / ``image_batch_deduplicate_*`` 完成。

设计原则（与 ``mclaw.shared`` 一致）：
  - 本包**不发 HTTP、不持鉴权/host**。``api_client`` 由调用方构造并注入
    （``ApiDispatcher(host=HOST, auth_fn=get_auth_header)``），见
    ``mclaw.shared.image_tools``。

权威来源：``cm_cloud_organize/scripts/image_deduplicator.py`` 的
``deduplicate_file_ids``（1:1 移植，批常量与降级行为完全对齐）。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from mclaw.api import ApiDispatcher
from mclaw.api.album.image_batch_deduplicate_api import (
    DEDUP_TASK_STATUS_COMPLETED,
    DEDUP_TASK_STATUS_EXPIRED,
    DEDUP_TASK_STATUS_FAILED,
    ImageBatchDeduplicateResultRequest,
    ImageBatchDeduplicateResultResponse,
    ImageBatchDeduplicateSubmitRequest,
)
from mclaw.api.album.image_deduplicate_api import (
    MAX_FILE_ID_LIST_SIZE,
    ImageDeduplicateRequest,
)
from mclaw.api.search_fusion import File

try:
    from mclaw.utils.logger import status_log
except Exception:  # pragma: no cover
    import logging

    def status_log(msg, logger=None, info_dict=None, server_type='API', stdout=False):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or logging.getLogger('mclaw.shared.organize.selector')).log(level, line)

try:
    from cli_timing import write_cli_output_line
except ImportError:
    def write_cli_output_line(line: str) -> None:
        print(line, flush=True)


__all__ = [
    'ImageDeduplicator',
    'MAX_FILE_ID_LIST_SIZE',
    'DEFAULT_DEDUP_MAX_WORKERS',
    'IMAGE_BATCH_DEDUP_POLL_INTERVAL_SEC',
    'IMAGE_BATCH_DEDUP_POLL_TIMEOUT_SEC',
    'IMAGE_BATCH_DEDUP_QUERY_MAX_FAILURES',
    'filter_files_by_ids',
]


#: 默认并行上限。依据并行基准（见 tests/organize/test_image_deduplicator.md §4）：
#: 4 线程对同一批 fileId 并发调去重，加速比 2.40×（串行 5.21s → 并行 2.17s）。
#: 接口异常仍由 deduplicate 的 except 整体降级兜底。
DEFAULT_DEDUP_MAX_WORKERS: int = 4

#: 批量去重 result 轮询间隔（秒）。先立即查一次（实测小任务 <2s 完成），未终态才 sleep。
IMAGE_BATCH_DEDUP_POLL_INTERVAL_SEC: float = 3.0
#: 批量去重 result 轮询总超时（秒）——卡死任务的最大等待，超时回退同步分批。
IMAGE_BATCH_DEDUP_POLL_TIMEOUT_SEC: float = 180.0
#: result 查询连续失败（HTTP 异常）上限，达到即回退。
IMAGE_BATCH_DEDUP_QUERY_MAX_FAILURES: int = 3


def _batch_fallback_log(reason: str) -> None:
    """批量去重回退同步的备查日志：只进 openclaw 日志，不进 stdout/回执。

    回退不算降级（同步链路结果等价），不打 ``[WARN]`` stdout 行；只有同步也
    失败时才由 ``deduplicate`` 的既有降级分支打 WARN。
    """
    status_log(f'批量去重不可用回退同步分批：{reason}', server_type='DEDUP')


def filter_files_by_ids(files: List[File], ordered_ids: List[str]) -> List[File]:
    """按 ``ordered_ids`` 顺序从 ``files`` 中取出对应 ``File``；缺失的 id 跳过。"""
    by_id = {f.file_id: f for f in files if f.file_id}
    return [by_id[fid] for fid in ordered_ids if fid in by_id]


class ImageDeduplicator:
    """相似图去重原子能力。

    ``api_client`` 由调用方注入（联邦 ``ApiDispatcher``），本类不持 host/鉴权。

    ``deduplicate`` **批量优先**：整单提交一个异步批量去重任务（无单次 1000 上限），
    轮询到已完成后下载结果文件与入参求交集；批量链路任何异常/畸形回退同步链路
    （见 ``_deduplicate_via_batch``）。同步链路经 ``api_client.album.image_deduplicate``
    调用，单次请求上限 ``MAX_FILE_ID_LIST_SIZE``（1000）；超限时分批调用并合并，
    迭代至可单次请求或列表收敛。**单轮内的分批并行执行**（``max_workers`` 控制
    并发上限，默认 ``DEFAULT_DEDUP_MAX_WORKERS=4``）；轮与轮之间串行（下一轮依赖
    上一轮 merged）。同步接口异常（HTTP 失败或业务失败，见 ``_call_api``）时降级
    返回（去重前清洗后的）入参 id 列表，不向上抛。
    """

    def __init__(
        self,
        api_client: ApiDispatcher,
        *,
        max_workers: Optional[int] = DEFAULT_DEDUP_MAX_WORKERS,
    ):
        self._api_client = api_client
        self._max_workers = max(1, int(max_workers or 1))

    def _call_api(self, file_ids: List[str]) -> List[str]:
        """单次调用去重接口，返回 ``nonsimilarFileIdList``（保持接口顺序）。

        业务失败（HTTP 200 + ``success=false``，如 20011/11000）不会在
        ``BaseSyncApi.execute`` 抛异常，须在此主动拦截——否则错误响应的
        ``nonsimilar_file_id_list=None`` 会被当作「全部相似」**清空整批**。
        此处抛出后由 ``deduplicate`` / ``deduplicate_batches`` 的既有降级
        分支保留入参，不向上抛。对齐旧封装 ``api_image_deduplicate``
        （旧版相册 HTTP 封装 ``cm_cloud_http.py``）的成功校验。
        """
        resp = self._api_client.album.image_deduplicate(
            ImageDeduplicateRequest(file_id_list=list(file_ids))
        )
        if not getattr(resp, 'success', True):
            raise RuntimeError(
                f'图片去重业务失败: code={getattr(resp, "code", "")} '
                f'message={getattr(resp, "message", "")}'
            )
        result = list(resp.nonsimilar_file_id_list or [])
        # 防御：成功但 nonsimilarFileIdList 缺失/为空。语义上每组重复必留
        # 一张、输入非空则非相似集非空，空结果即响应异常（文档标注字段可选 O），
        # 同样抛给上层降级保留，避免整批静默丢失
        if file_ids and not result:
            raise RuntimeError('图片去重返回空 nonsimilarFileIdList，疑似响应异常')
        return result

    def _call_batches(self, batches: List[List[str]]) -> List[str]:
        """对一批分片并行调用去重接口，按分片下标顺序拼接（保持结果顺序）。"""
        if not batches:
            return []
        if len(batches) == 1 or self._max_workers <= 1:
            # 串行：1 批或并发上限关闭，保持 1:1 行为，避免线程开销
            merged: List[str] = []
            for chunk in batches:
                merged.extend(self._call_api(chunk))
            return merged
        # 并行：按下标收集，保持与串行一致的拼接顺序
        results: List[List[str]] = [[]] * len(batches)
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._call_api, chunk): idx
                for idx, chunk in enumerate(batches)
            }
            for fut, idx in futures.items():
                results[idx] = fut.result()
        merged: List[str] = []
        for chunk_result in results:
            merged.extend(chunk_result)
        return merged

    def deduplicate_batches(self, batches: List[List[str]]) -> List[str]:
        """对预切好的多批（每批 ≤ ``MAX_FILE_ID_LIST_SIZE``）单趟并行去重，按批序拼回。

        与 ``deduplicate`` 的区别：不迭代收敛，**单趟**完成；**逐批异常隔离**——
        某批 HTTP 失败时该批降级为返回其入参 id（打 WARN），其余批照常，整体不向上抛。
        批切分（含同时间不拆等边界）由调用方负责；本方法只负责并行执行 + 拼回。
        """
        cleaned = [[fid for fid in batch if fid] for batch in batches]
        cleaned = [batch for batch in cleaned if batch]
        if not cleaned:
            return []

        def _run_one(chunk: List[str]) -> List[str]:
            try:
                return self._call_api(chunk)
            except Exception as exc:  # noqa: BLE001 - 单批降级，不影响其他批
                write_cli_output_line(
                    f'[WARN] 图片去重接口调用失败，该批 {len(chunk)} 个 fileId 降级保留：{exc}'
                )
                return list(chunk)

        if len(cleaned) == 1 or self._max_workers <= 1:
            merged: List[str] = []
            for chunk in cleaned:
                merged.extend(_run_one(chunk))
            return merged

        results: List[List[str]] = [[] for _ in cleaned]
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_to_idx = {
                pool.submit(_run_one, chunk): idx
                for idx, chunk in enumerate(cleaned)
            }
            for fut, idx in future_to_idx.items():
                results[idx] = fut.result()
        merged = []
        for chunk_result in results:
            merged.extend(chunk_result)
        return merged

    def _submit_batch_task(self, file_ids: List[str]) -> str:
        """提交批量去重任务，返回 taskId；业务失败/无 taskId 返回空串（回退）。"""
        resp = self._api_client.album.image_batch_deduplicate_submit(
            ImageBatchDeduplicateSubmitRequest(file_id_list=list(file_ids))
        )
        if not getattr(resp, 'success', True):
            _batch_fallback_log(
                f'submit 业务失败 code={getattr(resp, "code", "")} '
                f'message={getattr(resp, "message", "")}'
            )
            return ''
        task_id = str(getattr(resp, 'task_id', '') or '')
        if not task_id:
            _batch_fallback_log('submit 未返回 taskId')
        return task_id

    def _poll_batch_task(
        self, task_id: str
    ) -> Optional[ImageBatchDeduplicateResultResponse]:
        """轮询批量任务至终态：已完成（2）返回响应；失败/过期/超时/查询失败返回 None。

        先立即查一次，未终态再 sleep。result 查询 ``success=false``（HTTP 200
        业务失败，不抛异常）须显式拦截——与 ``_call_api`` 同款教训。未知
        taskStatus 值按未终态继续轮询，由超时兜底。
        """
        deadline = time.monotonic() + IMAGE_BATCH_DEDUP_POLL_TIMEOUT_SEC
        query_failures = 0
        first = True
        while time.monotonic() < deadline:
            if not first:
                time.sleep(IMAGE_BATCH_DEDUP_POLL_INTERVAL_SEC)
            first = False
            try:
                resp = self._api_client.album.image_batch_deduplicate_result(
                    ImageBatchDeduplicateResultRequest(task_id=task_id)
                )
            except Exception as exc:  # noqa: BLE001 - 查询失败计数重试，达上限回退
                query_failures += 1
                if query_failures >= IMAGE_BATCH_DEDUP_QUERY_MAX_FAILURES:
                    _batch_fallback_log(f'result 查询连续失败 {query_failures} 次: {exc}')
                    return None
                continue
            if not getattr(resp, 'success', True):
                _batch_fallback_log(
                    f'result 业务失败 code={getattr(resp, "code", "")} '
                    f'message={getattr(resp, "message", "")}'
                )
                return None
            query_failures = 0
            status = int(getattr(resp, 'task_status', 0) or 0)
            if status == DEDUP_TASK_STATUS_COMPLETED:
                return resp
            if status in (DEDUP_TASK_STATUS_FAILED, DEDUP_TASK_STATUS_EXPIRED):
                _batch_fallback_log(f'taskStatus={status}（3-失败 / 4-已过期）')
                return None
            # 0/1（待处理/处理中）及未知新增状态 → 继续轮询
        _batch_fallback_log(
            f'轮询超时 {IMAGE_BATCH_DEDUP_POLL_TIMEOUT_SEC}s 未到终态（taskId={task_id}）'
        )
        return None

    def _intersect_batch_result(
        self,
        resp: ImageBatchDeduplicateResultResponse,
        file_ids: List[str],
    ) -> Optional[List[str]]:
        """已完成响应 → 去重后 id 列表：取 ``result_file_ids`` 求入参交集（保持入参顺序）。

        防线：``result_file_ids`` 为空（respUrl 缺失 / API 层下载解析失败置 None）、
        ``filesNumber`` 与提交数不符（结果未覆盖全量输入，交集口径会错杀未覆盖
        部分）、交集为空，均回退。
        """
        txt_ids = getattr(resp, 'result_file_ids', None)
        if not txt_ids:
            _batch_fallback_log('result_file_ids 为空（respUrl 缺失或结果文件下载/解析失败）')
            return None
        files_number = int(getattr(resp, 'files_number', 0) or 0)
        if files_number and files_number != len(file_ids):
            _batch_fallback_log(
                f'filesNumber={files_number} 与提交数 {len(file_ids)} 不符，结果未覆盖全量'
            )
            return None
        txt_set = set(txt_ids)
        kept = [fid for fid in file_ids if fid in txt_set]
        if not kept:
            _batch_fallback_log('txt 与入参交集为空')
            return None
        return kept

    def _deduplicate_via_batch(self, file_ids: List[str]) -> Optional[List[str]]:
        """批量去重优先路径：整单一个异步任务 → 轮询 → 结果文件交集。

        返回去重后 id 列表；**None = 本路径不可用，调用方回退同步分批**。全链路
        任何异常在此收敛（含 dispatcher 未注册批量方法的 AttributeError，兼容
        旧 fake），不向上抛、不打 stdout；回退原因仅落 openclaw 日志备查。
        """
        try:
            task_id = self._submit_batch_task(file_ids)
            if not task_id:
                return None
            resp = self._poll_batch_task(task_id)
            if resp is None:
                return None
            return self._intersect_batch_result(resp, file_ids)
        except Exception as exc:  # noqa: BLE001 - 任何意外一律回退同步
            _batch_fallback_log(f'异常: {exc}')
            return None

    def deduplicate(self, file_ids: List[str]) -> List[str]:
        """对 fileId 列表做相似图去重，返回去重后的 fileId 列表。

        **批量优先**：先整单提交异步批量去重任务（无单次 1000 上限），轮询到
        已完成后下载结果文件（全程内存）与入参求交集；批量链路任何异常/畸形
        回退同步链路（二选一，不混合）。

        同步链路：单次请求上限 ``MAX_FILE_ID_LIST_SIZE``；超限时分批调用并在
        合并后迭代再跑一轮，直至结果可单次请求或列表收敛（迭代循环，避免递归
        深度风险）。**单轮内的分批并行执行**（并发上限 ``max_workers``，默认 4）；
        轮间串行。接口不稳定时降级：捕获到调用异常后输出告警并返回未去重
        （已清洗）的 fileId 列表，避免阻塞后续相册生成流程。
        """
        ids = list(dict.fromkeys(fid for fid in file_ids if fid))
        if not ids:
            return []

        batch_result = self._deduplicate_via_batch(ids)
        if batch_result is not None:
            return batch_result

        try:
            current = ids
            while True:
                if len(current) <= MAX_FILE_ID_LIST_SIZE:
                    return self._call_api(current)
                batches = [
                    current[i : i + MAX_FILE_ID_LIST_SIZE]
                    for i in range(0, len(current), MAX_FILE_ID_LIST_SIZE)
                ]
                merged = self._call_batches(batches)
                merged = list(dict.fromkeys(merged))
                if merged == current:
                    return merged
                current = merged
        except Exception as exc:
            write_cli_output_line(
                f'[WARN] 图片去重接口调用失败，降级使用未去重的 fileId 列表：{exc}'
            )
            return ids

    def deduplicate_files(self, files: List[File]) -> Tuple[List[File], int]:
        """相似图去重并映射回 ``File`` 列表。返回 ``(去重后 files, 移除张数)``。"""
        before = len(files)
        if before == 0:
            return [], 0
        file_ids = [f.file_id for f in files if f.file_id]
        deduped_ids = self.deduplicate(file_ids)
        result = filter_files_by_ids(files, deduped_ids)
        return result, before - len(result)
