#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio/video 动态卡片的媒体富化（duration + contentSchedule）。

仅对 audio-dynamic/video-dynamic 的卡片展示行（前 ``CARD_DISPLAY_LIMIT`` 条）富化，
非全量（full 模式可能几百条音视频，逐文件串行 API 会撑爆软预算 500s）。

- ``duration``（int ms，亚秒精度）：来自 getPreviewInfo（``/personalSaas/videoPreview/
  getPreviewInfo``）。公共库未封装该端点 → 本模块手写（公共库 cloud_auth 鉴权 + requests），
  属公共库可议点（docs/audio_video_dynamic_design.md §6），未擅动公共库。
- ``contentSchedule``（int ms）：来自 query_file_schedules（公共库已封装
  ``dispatcher.personal_saas.query_file_schedules``，``PlayInfo.playback_progress`` 已 int-ms）。

容错（best-effort，永不阻断搜索终态）：
- 单条 getPreviewInfo / query_file_schedules 失败 → 对应 key 省略；
- 富化整体异常 / 超预算守卫超时 → 返回空映射，卡片照常出（无 duration/contentSchedule）。
对齐旧技能 query_personal_dynamic 的 audioList/videoList 行为。

并发：duration 逐文件 getPreviewInfo（无批量端点）改 ``ThreadPoolExecutor`` 并发拉取
（``_ENRICH_MAX_WORKERS`` 线程上限），避免 10 条串行最坏 ≈150s 顶破 view 快速承诺与
full 的 600s 进程超时；鉴权头按请求即时读取（公共库 ``get_auth_header`` 契约：
每次新建实例、禁止跨请求复用做进程内缓存），并发安全。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

#: getPreviewInfo 超时（秒）；单文件请求，取保守值避免长尾拖慢卡片
_PREVIEW_TIMEOUT_SEC = 15

#: duration 并发拉取的线程上限（前 10 条，5 worker 折中：墙钟最坏 ≈30s，
#: 兼顾对 getPreviewInfo 端点的瞬时压力）
_ENRICH_MAX_WORKERS = 5

#: duration 并发拉取的整体超时（秒）——预算守卫：超此时长未完成的请求放弃，
#: 已拿到的 duration 保留、未拿到的省略，避免富化拖垮 view 快速承诺 / full 的 600s 进程超时
_ENRICH_DEADLINE_SEC = 30

#: contentType → getPreviewInfo 的 category 词形（getPreviewInfo 收 'audio'/'video'）
_CT_TO_PREVIEW_CATEGORY = {2: 'audio', 3: 'video'}


def _get_preview_duration(file_id: str, content_type: int) -> Optional[int]:
    """调 getPreviewInfo 取媒体时长（秒，可能小数字符串）→ int ms。

    失败返回 None（调用方省略 duration key，不阻断）。host/鉴权头读取与请求发送
    一并纳入异常兜底：任何非预期异常（含非 ``RequestException`` 的鉴权异常）
    都降级为 None，不向上传播。
    """
    import requests  # 懒加载：仅 audio/video 动态触发，不污染其他场景的 import 面
    from mclaw.shared.cm_cloud.cloud_auth import get_cloud_auth_headers, get_cloud_host
    from mclaw.api.app_endpoint_map import resolve_url

    category = _CT_TO_PREVIEW_CATEGORY.get(content_type, 'video')
    try:
        url = resolve_url(get_cloud_host(), '/richlifeApp/personalSaas/videoPreview/getPreviewInfo')
        resp = requests.post(
            url,
            json={'fileId': file_id, 'category': category},
            headers=get_cloud_auth_headers(),
            timeout=_PREVIEW_TIMEOUT_SEC,
        )
    except Exception:  # noqa: BLE001 best-effort：网络/鉴权/配置任何异常都降级 None
        return None
    if resp.status_code != 200:
        return None
    try:
        result = resp.json()
    except ValueError:
        return None
    if not (result.get('success') and str(result.get('code')) == '0000'):
        return None
    data = result.get('data') or {}
    meta = data.get('meta') or {}
    dur_raw = meta.get('duration')
    if dur_raw is None or dur_raw == '':
        return None
    try:
        return int(float(str(dur_raw)) * 1000)  # 秒（带小数）→ ms int
    except (ValueError, TypeError):
        return None


def _query_schedules(file_ids: List[str], content_types: List[int]) -> Dict[str, int]:
    """调公共库 query_file_schedules 取播放进度，返回 {fileId: playbackProgress(ms)}。

    失败返回空 dict（调用方省略 contentSchedule key）。
    """
    if not file_ids:
        return {}
    from mclaw.api.personal_saas.query_file_schedules_api import QueryFileSchedulesRequest
    from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher

    try:
        resp = get_cloud_dispatcher().personal_saas.query_file_schedules(
            QueryFileSchedulesRequest(
                fileIdList=file_ids,
                contentTypeList=content_types,
            )
        )
    except Exception:
        return {}
    if not getattr(resp, 'success', False):
        return {}
    return {
        str(info.file_id): int(info.playback_progress)
        for info in (resp.result_data or [])
        if info.file_id
    }


def enrich_media_rows(
    rows: List[Dict],
    content_type: Optional[int],
) -> Dict[str, Dict[str, int]]:
    """对前 N 条 audio/video 行富化，返回 ``{fileId: {duration, contentSchedule}}`` 映射。

    - 仅 audio-dynamic/video-dynamic 调用方传入（``content_type in (2, 3)``）；
      其余场景调用方应直接跳过本函数（零开销）。
    - ``rows`` 为已归一化的展示行（含 fileId）；本函数取前 N 条的 fileId 富化。
    - duration 逐文件 getPreviewInfo（亚秒精度）**并发**拉取（``_ENRICH_MAX_WORKERS``
      线程上限 + ``_ENRICH_DEADLINE_SEC`` 整体超时守卫）；contentSchedule 批量
      query_file_schedules。

    best-effort：任何异常（单条失败 / 整体超预算 / 未预期错误）都降级为「省略对应
    key 或返回空映射」，永不抛出——富化失败不影响搜索终态与卡片输出。
    """
    if content_type not in (2, 3):
        return {}
    ct_list = [content_type]
    file_ids = [str(r.get('fileId') or '') for r in rows if r.get('fileId')]
    if not file_ids:
        return {}
    try:
        # contentSchedule：批量一次
        schedule_map = _query_schedules(file_ids, ct_list)
        # duration：并发拉取（getPreviewInfo 无批量端点）；整体超 _ENRICH_DEADLINE_SEC
        # 未完成的放弃 → 该 fileId 省略 duration key
        duration_map = _fetch_durations_concurrent(file_ids, content_type)
    except Exception:  # noqa: BLE001 富化整体降级，永不阻断搜索终态
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for fid in file_ids:
        entry: Dict[str, int] = {}
        dur = duration_map.get(fid)
        if dur is not None:
            entry['duration'] = dur
        if fid in schedule_map:
            entry['contentSchedule'] = schedule_map[fid]
        if entry:
            out[fid] = entry
    return out


def _fetch_durations_concurrent(
    file_ids: List[str], content_type: int
) -> Dict[str, int]:
    """并发拉取 duration，返回 ``{fileId: durationMs}``（失败的 fileId 不出现）。

    整体超 ``_ENRICH_DEADLINE_SEC`` 即放弃未完成项（best-effort，不阻断）：
    已收集的部分结果保留返回，不让 TimeoutError 穿出（否则调用方兜底会把
    已拿到的 duration 连同 contentSchedule 一起吞成空映射）。线程池用
    ``shutdown(wait=False, cancel_futures=True)`` 退出：不 join 残余线程
    （在途请求靠自身 requests 超时自然收敛），保证墙钟 ≈ deadline 而非
    等全部线程结束。
    """
    out: Dict[str, int] = {}
    pool = ThreadPoolExecutor(max_workers=_ENRICH_MAX_WORKERS)
    try:
        futures = {
            pool.submit(_get_preview_duration, fid, content_type): fid
            for fid in file_ids
        }
        try:
            for future in as_completed(futures, timeout=_ENRICH_DEADLINE_SEC):
                fid = futures[future]
                try:
                    dur = future.result()
                except Exception:  # noqa: BLE001 单条失败 → 省略 duration
                    continue
                if dur is not None:
                    out[fid] = dur
        except TimeoutError:
            pass  # 超时放弃未完成项，已收集的部分结果照常返回
        return out
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
