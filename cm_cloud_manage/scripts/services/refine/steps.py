#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refine 编排：对 search.jsonl 去重/精选，产 dedup.jsonl/select.jsonl 子集。

管道：打开会话读 search.jsonl（部分快照先过全量保障续拉，与 organize plan 同款「全量保障」；
续拉期间公共库 runner 打 record=progress 进度行）→ 可选聚类（``--bucket`` 给出则 per-bucket
refine，逐桶变换；否则整集当一桶变换）→ 写子集 jsonl（带 per-row bucket 标签）→ meta 记产物
→ refine 回执 + nextSteps + 结果预览卡（公共库 preview_cards 静态卡，恒截断展示，不打全量）。

**不 import ``services.organize.steps``**：subset 读写独立（``subset_io``），变换/聚类/全量
续拉直连公共库 ``transforms``/``cluster_ops``（全量保障已本地化 ``services/search_fetch``），避免 organize/common
循环耦合（戒律见 memory common-lib-organize-circular-import）。fire-and-forget，不触网根
目录（refine 不创建云盘目录，无 ``_resolve_root``）。
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Tuple

from cli_timing import write_cli_output_line
from utils.config import (
    MEMORY_PHOTO_GATE_HINT,
    REFINE_NO_SURVIVORS_SAY,
    REFINE_SAY_BUCKET_DETAIL_MAX,
    REFINE_SELECT_EMPTY_BUCKETS,
    REFINE_SELECT_EMPTY_BUCKETS_MANY,
    REFINE_SELECT_UNDER_PICK_BUCKETS,
    REFINE_SELECT_UNDER_PICK_BUCKETS_MANY,
    REFINE_SELECT_UNDER_PICK_WHOLE,
    REFINE_TRANSFORM_MAX_WORKERS,
    USE_SELECT_PHOTO,
)
from mclaw.api.search_fusion import File
from mclaw.shared.cm_cloud.card_meta import build_search_result_summary
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.organize.bucket.unknown_labels import sort_bucket_keys
from mclaw.shared.organize.cluster_ops import flatten_tree, run_cluster
from mclaw.shared.organize.dedup import (
    DEFAULT_DEDUP_MAX_WORKERS,
    MemoryPhotoFilter,
    collapse_exact_duplicates,
)
from mclaw.shared.organize.select_photo import select_photos
from mclaw.utils.logger import openclaw_logger, status_log
from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)
from mclaw.shared.organize.preview_cards import (
    BUCKET_CARD_ROW_LIMIT,
    file_to_preview_row,
    iter_bucket_grouped_card_lines,
    render_static_card,
)
from mclaw.shared.organize.selector import ImageDeduplicator, QualitySelector
# 复用 transforms 的 _is_image/_file_id（与本地原实现字节相同；跨模块 import 私有符号
# 在本项目有先例：refine/subset_io.py 已 import _HEADER_RECORDS）。
from mclaw.shared.organize.transforms import _is_image, _file_id

from services.errors import OperationServiceError, ensure_full_search_results
from services.refine.merge import run_merge
from services.refine.subset_io import (
    is_merged_header,
    read_subset,
    read_subset_header,
    write_subset,
)
from services.stdout_receipt import Handle, emit_handle, ok_meta

if TYPE_CHECKING:
    from cli.refine import RefineTask  # noqa: F401 仅供类型注解（运行期零依赖）


__all__ = ['run_refine']

#: nextSteps 命令模板用的 main.py 绝对路径（services/<pkg>/steps.py 的 parents[2] 即 scripts 目录）
_MAIN_PY = str(Path(__file__).resolve().parents[2] / 'main.py')


def run_refine(task: 'RefineTask') -> None:
    # 0) merge 走独立编排（并多 jsonl 产新语料，docs/cli_design.md §9）
    if getattr(task, 'kind', '') == 'merge':
        run_merge(task)
        return

    # 1) 打开会话读语料（search.jsonl / merged.jsonl；子集不可直接 refine）
    try:
        session = OrganizeSession.open(task.from_handle)
    except OrganizeSessionError as exc:
        raise OperationServiceError(str(exc)) from exc
    input_path = session.dir / task.input_file
    if not input_path.is_file():
        raise OperationServiceError(
            f'会话 {session.id} 没有 {task.input_file}；'
            + (
                '请先用 search 搜索（产 handle）。'
                if task.input_file == 'search.jsonl'
                else '请先用 refine --kind merge 生成（如 op_<6位编码>/merged.jsonl）。'
            )
        )

    # 2) 全量保障（search：isFull≠true 就地续拉回写，让出 FetchYield 原样上抛）；
    #    merged 是终态语料（恒 isFull=true），异常 false 报错重建、绝不续拉。
    header_in = read_subset_header(input_path)
    if task.input_file == 'merged.jsonl':
        if not is_merged_header(header_in):
            raise OperationServiceError(
                f'{task.input_file} 不是合法的 merge 产物'
                '（header 缺 resultRole=merged 标记）；请重新 merge 生成。'
            )
        if not bool(header_in.get('isFull')):
            raise OperationServiceError(
                f'{task.input_file} 的 isFull≠true，属于异常产物；请重新 merge 重建。'
            )
    elif not bool(header_in.get('isFull')):
        header_in = ensure_full_search_results(str(input_path))

    files = [f for _, f in read_subset(input_path)]
    if not files:
        raise OperationServiceError(
            '搜索结果无有效文件记录；请先用 search 搜索并落盘'
        )

    # 3) 可选聚类（--bucket 给出 → per-bucket refine；否则整集 refine）
    per_bucket = bool(task.mode)
    files_with_bucket: List[Tuple[str, File]] = []
    if per_bucket:
        try:
            flat, tree = run_cluster(
                files,
                mode=task.mode,
                bucket=task.bucket,
                buckets=list(task.buckets),
            )
        except ValueError as exc:
            raise OperationServiceError(f'参数错误：聚类失败：{exc}') from exc
        # refine 子集只承载单层 bucket 标签：hierarchical 降维成 'A_B' 拼名（flatten_tree）
        if flat is None and tree is not None:
            flat = flatten_tree(tree)
        if not flat:
            raise OperationServiceError('聚类结果为空；请检查 --bucket 维度参数')
        for key in sort_bucket_keys(flat.keys()):
            for f in flat.get(key) or []:
                files_with_bucket.append((key, f))
    else:
        for f in files:
            files_with_bucket.append(('', f))

    # 4) 变换：select 与回忆故事精选同款（memory 固定每桶 top-50、refine 用 --pick N；
    #    memory 的素材不足门槛不进 refine）——照片质量门（MemoryPhotoFilter：证件/截图
    #    等标签黑名单 + 无拍摄时间剔除）→ 精确去重 → 相似图去重 → 质量分 top-N；
    #    dedup 不加门、只做两步去重。非图片剔除（不进子集）。不走公共库 transform_leaf_files
    #    （固定 top-50 无 pick 旋钮），直连同款原语组装。
    survivors: List[Tuple[str, File]] = []
    # select 且分桶：记录精选后不足 --pick 的桶（保留数 < pick 且 >0），
    # 供 say「已全部为你选出」提示（判定用变换前桶大小对比最终保留数）
    short_buckets: List[Tuple[str, int]] = []
    # select 且分桶：记录精选后整桶清空的桶（AI 选图空 / 质量门剔空），
    # 供 say「已跳过」桶级提示（否则桶静默消失、总数变少无从解释）
    empty_buckets: List[str] = []
    if per_bucket:
        groups: Dict[str, List[File]] = {}
        for bk, f in files_with_bucket:
            groups.setdefault(bk, []).append(f)
        ordered_keys = sort_bucket_keys(groups.keys())
        # 多桶并行：各桶 _transform_bucket 并行（上限 REFINE_TRANSFORM_MAX_WORKERS），按桶序
        # 提交+收集，survivors/short_buckets/落盘顺序与串行一致；单桶/上限≤1 串行兜底。
        # 外层并行时桶内相似图去重降 max_workers=1 收敛嵌套（外 N × 内 4 瞬时并发）。
        parallel = len(ordered_keys) > 1 and REFINE_TRANSFORM_MAX_WORKERS > 1
        inner_dedup_workers = 1 if parallel else DEFAULT_DEDUP_MAX_WORKERS
        if parallel:
            with ThreadPoolExecutor(max_workers=REFINE_TRANSFORM_MAX_WORKERS) as pool:
                futures = [
                    pool.submit(
                        _transform_bucket, groups[bk], task,
                        dedup_max_workers=inner_dedup_workers,
                    )
                    for bk in ordered_keys
                ]
                kept_lists = [fut.result() for fut in futures]
        else:
            kept_lists = [
                _transform_bucket(groups[bk], task, dedup_max_workers=inner_dedup_workers)
                for bk in ordered_keys
            ]
        for bk, kept in zip(ordered_keys, kept_lists):
            if task.kind == 'select' and task.pick > 0 and 0 < len(kept) < task.pick:
                short_buckets.append((bk, len(kept)))
            if task.kind == 'select' and task.pick > 0 and not kept:
                empty_buckets.append(bk)
            survivors.extend((bk, f) for f in kept)
    else:
        survivors = [('', f) for f in _transform_bucket(files, task)]

    if not survivors:
        # 零保留：正常 ok 收束（非 error），落空子集供追溯；不出卡、不发 handle/next
        out_path = write_subset(
            session_dir=session.dir,
            kind=task.kind,
            files_with_bucket=[],
            source_header=header_in,
            refine_cluster_args={
                'mode': task.mode,
                'bucket': task.bucket,
                'buckets': list(task.buckets),
            },
            pick=task.pick,
        )
        rel_path = f'{session.id}/{out_path.name}'
        session.merge_meta({
            f'refine_{task.kind}_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            f'refine_{task.kind}_file': out_path.name,
            f'refine_{task.kind}_count': 0,
        })
        ok_meta(
            'refine',
            # select 追加门规则说明；dedup 不加门勿附加（误导死因）
            say_to_user=(
                REFINE_NO_SURVIVORS_SAY
                + (MEMORY_PHOTO_GATE_HINT if task.kind == 'select' else '')
            ),
            data={
                'outputFile': rel_path,
                'fileCount': 0,
            },
        )
        return

    # 5) 写子集 jsonl（带 per-row bucket）
    out_path = write_subset(
        session_dir=session.dir,
        kind=task.kind,
        files_with_bucket=survivors,
        source_header=header_in,
        refine_cluster_args={
            'mode': task.mode,
            'bucket': task.bucket,
            'buckets': list(task.buckets),
        },
        pick=task.pick,
    )

    # 6) meta 记子集产物
    session.merge_meta({
        f'refine_{task.kind}_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        f'refine_{task.kind}_file': out_path.name,
        f'refine_{task.kind}_count': len(survivors),
    })

    # 7) 回执：refine 一条 meta + handle 行（handle 在卡片之后收尾：openclaw exec
    #    输出超限保留尾部、丢头部，协议行放最后才不被截掉）
    #    data 只留用户关心的数（规则 11）：outputFile（下游 plan --from 消费）、fileCount
    #    （去重/精选后保留数）、buckets（分桶时每桶保留数——用户问「每桶剩多少」读它转述）。
    #    总数（去重前）进 sayToUser 文案；handle（handle 行已带 id）、kind（命令是模型
    #    自己发的）、精确/相似移除拆分（对用户无意义，降级由公共库 [WARN] 行承载）、
    #    picked/bucketCount（fileCount / len(buckets) 已覆盖）不进回执。
    bucket_counts: Dict[str, int] = {}
    for bk, _f in survivors:
        if bk:
            bucket_counts[bk] = bucket_counts.get(bk, 0) + 1
    rel_path = f'{session.id}/{out_path.name}'  # 供 plan --from 直接用
    verb = '精选' if task.kind == 'select' else '去重'
    say = f'{len(files)} 个文件{verb}后保留 {len(survivors)} 个。'
    buckets_sorted: Dict[str, int] = {
        bk: bucket_counts[bk] for bk in sort_bucket_keys(bucket_counts)
    }
    if per_bucket and buckets_sorted and len(buckets_sorted) <= REFINE_SAY_BUCKET_DETAIL_MAX:
        say += '详情：' + '; '.join(
            f'{bk}:{n}张' for bk, n in buckets_sorted.items()
        )
    # select 未选满提示（文案模板集中 config.py，2026-09-03 用户定案，用户向
    # 「已尽力选出」口吻，不用「素材不足」缺口腔）：整集看总数、分桶点名未选满桶
    #（桶多不点名）
    if task.kind == 'select' and task.pick > 0:
        if per_bucket and short_buckets:
            if len(short_buckets) <= REFINE_SAY_BUCKET_DETAIL_MAX:
                names = '、'.join(f'「{bk}」' for bk, _n in short_buckets)
                say += (REFINE_SELECT_UNDER_PICK_BUCKETS
                        .replace('<buckets>', names)
                        .replace('<pick>', str(task.pick)))
            else:
                say += REFINE_SELECT_UNDER_PICK_BUCKETS_MANY.replace(
                    '<pick>', str(task.pick))
        elif not per_bucket and len(survivors) < task.pick:
            say += REFINE_SELECT_UNDER_PICK_WHOLE.replace(
                '<kept>', str(len(survivors)))
    # 分桶 select 整桶精选后为空：桶级点名告知（桶静默消失会让总数变少无从解释；
    # 点名上限同详情阈值，超限只报桶数）
    if per_bucket and task.kind == 'select' and empty_buckets:
        if len(empty_buckets) <= REFINE_SAY_BUCKET_DETAIL_MAX:
            names = '、'.join(f'「{bk}」' for bk in empty_buckets)
            say += (REFINE_SELECT_EMPTY_BUCKETS
                    .replace('<count>', str(len(empty_buckets)))
                    .replace('<buckets>', names))
        else:
            say += REFINE_SELECT_EMPTY_BUCKETS_MANY.replace(
                '<count>', str(len(empty_buckets)))
    merge_hint = ' [--merge-into <名>]' if per_bucket else ' [--bucket …] / [--parent-path <名>]'
    plan_cmd = (
        f'python3 {_MAIN_PY} organize --step plan '
        f'--from {rel_path}{merge_hint}'
    )
    data: Dict[str, object] = {
        'outputFile': rel_path,
        'fileCount': len(survivors),
    }
    if per_bucket:
        data['buckets'] = buckets_sorted
    ok_meta(
        'refine',
        say_to_user=say,
        next_steps={'plan': plan_cmd},
        data=data,
    )
    # 8) 结果预览卡：恒截断展示（不打全量列表，续拉完成也一样）
    _emit_result_cards(survivors, task=task, per_bucket=per_bucket)
    # 9) handle 行收尾（meta 先发、卡片之后补发；公共库 emit_handle）
    emit_handle(Handle(id=rel_path, params={
        'kind': task.kind,
        'bucket': task.bucket,
    }))


def _emit_result_cards(
    survivors: List[Tuple[str, File]], *, task: 'RefineTask', per_bucket: bool
) -> None:
    """结果预览卡（公共库 ``preview_cards`` 静态卡，维持 cm_cloud_organize 做法）。

    - 分桶精选：每桶一张卡，公共库默认上限（≤5 桶 × 每桶 10 行，桶序）；桶数超上限
      时首卡 summary 前自动加「总共x个分类，下面只展示其中的x个分类。」提示
      （即「仅展示部分类别的精选结果」），卡内标题为精选口径。
    - 去重（整集或分桶）：合并后一张卡、前 10 行，summary 去重口径。
    - 整集精选：一张卡、前 10 行，summary 精选口径。

    卡片只承载「看个大概」：全量明细在子集 jsonl / data.buckets，截断数字由各卡
    summary 自述；子集仅含图片（非图片在变换时已剔除）。
    """
    files = [f for _, f in survivors]
    if task.kind == 'select' and per_bucket:
        buckets: Dict[str, List[File]] = {}
        for bk, f in survivors:
            buckets.setdefault(bk, []).append(f)
        for line in iter_bucket_grouped_card_lines(
            buckets, file_type='image', top=task.pick
        ):
            write_cli_output_line(line)
        return
    rows = [
        file_to_preview_row(f, index=idx, file_type='image')
        for idx, f in enumerate(files[:BUCKET_CARD_ROW_LIMIT], start=1)
    ]
    summary = build_search_result_summary(
        file_type='image',
        total=len(files),
        shown=len(rows),
        top=task.pick if task.kind == 'select' else 0,
        dedup=task.kind == 'dedup',
    )
    for line in render_static_card(
        file_type='image', rows=rows, summary=summary
    ).splitlines():
        write_cli_output_line(line)


def _transform_bucket(
    files: List[File], task: 'RefineTask', *, dedup_max_workers: int = DEFAULT_DEDUP_MAX_WORKERS,
) -> List[File]:
    """单桶变换：select 与回忆故事精选同款（门 → 两步去重 → top-N）；dedup 只做去重。

    与公共库 ``refine_for_memory`` 的逐桶序列一致（仅缺素材不足门槛、top-N 用
    ``--pick``）：select 先过 ``MemoryPhotoFilter`` 照片质量门（事物标签黑名单 +
    无拍摄时间/1970-01-01 剔除，缺 takenAt 全剔是预期），再两步去重，再按 imgQuality
    取前 N。dedup 不加门。非图片不参与、也不进子集（直接剔除，2026-09-11 定案）。

    - ``MemoryPhotoFilter.filter`` 本地照片过滤（零网络，仅 select）→
      ``collapse_exact_duplicates`` 本地精确去重（零网络）→
      ``ImageDeduplicator.deduplicate_files`` 相似图 API 去重（接口失败降级保留入参，
      公共库打 ``[WARN]`` 行告知，回执不重复透出）。
    - ``pick > 0``（select）：桶内按 imgQuality 取前 N（缺质量分按 0 分计，
      并列按 fileId 升序——公共库 ``select_global_top_n`` 的排序键）。
    - ``USE_SELECT_PHOTO``（仅 select 且 pick>0）：门+精确去重后，「相似图 API 去重 +
      imgQuality top-N」两步换成 ``select_photos`` AI 选图异步任务（count=pick，不传
      query/threshold）；提交/轮询异常打 traceback 日志并回退旧两步，SUCCESS 空结果
      不回退（真实精选为空，走零保留 ok 回执）。

    ``dedup_max_workers`` 收敛嵌套并行：外层按桶并行时调用方传 1（桶内相似图去重串行，
    避免外 N × 内 4 瞬时并发），单桶/串行用默认 ``DEFAULT_DEDUP_MAX_WORKERS``。

    只返回存活文件（回执数从 survivors 现算，TransformStats 拆分计数已随回执极简删除）。
    """
    images = [f for f in files if _is_image(f)]
    if not images:
        # 整桶无图片：无精选/去重对象，非图片也不进子集 → 空
        return []

    kept_imgs: List[File] = images

    # 0) 照片质量门（仅 select）：回忆故事同款 MemoryPhotoFilter——证件/截图等标签
    #    黑名单 + 无拍摄时间（含 1970-01-01）剔除；整桶图片被剔空时非图片仍透传
    #    （下方按 survivors 集过滤自然兜住）
    if task.kind == 'select':
        kept_imgs, _ = MemoryPhotoFilter().filter(kept_imgs)

    # 1) 精确去重：本地 contentHash（零网络），完全相同的图免费摘除
    kept_imgs, _ = collapse_exact_duplicates(kept_imgs)

    # 2+3) 选图：USE_SELECT_PHOTO 时（仅 select 且 pick>0）「相似图 API 去重 +
    #      imgQuality top-N」两步换成 AI 选图异步任务；异常打日志回退旧两步。
    #      SUCCESS 但 goodImages 空 = 真实精选结果为空（不回退，走既有空结果路径）
    select_ok = False
    if USE_SELECT_PHOTO and task.kind == 'select' and task.pick > 0 and kept_imgs:
        try:
            kept_imgs = select_photos(
                get_cloud_dispatcher(), kept_imgs, count=task.pick
            )
            select_ok = True
        except Exception:
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[WARN] AI 选图失败，已回退相似图去重+质量评分。exc={flat_exc}',
                logger=openclaw_logger,
                info_dict={
                    'api': 'select_photos',
                    'kind': task.kind,
                    'pick': task.pick,
                },
                server_type='SYNC',
                stdout=True,
            )

    if not select_ok:
        # 2) 相似图去重：调相似图 API（接口失败由公共库降级保留入参并打 [WARN] 行）
        if kept_imgs:
            deduper = ImageDeduplicator(
                get_cloud_dispatcher(), max_workers=dedup_max_workers
            )
            kept_imgs, _ = deduper.deduplicate_files(kept_imgs)

        # 3) 精选：桶内图片按 imgQuality 取前 N（缺分按 0 计，并列 fileId 升序）
        if task.pick > 0 and kept_imgs:
            kept_imgs = QualitySelector().select_global_top_n(kept_imgs, task.pick)

    # 按保留 fileId 集过滤回原文件顺序（非图片剔除，只回存活图片）
    survivors = {_file_id(f) for f in kept_imgs}
    return [
        f for f in files
        if _is_image(f) and _file_id(f) in survivors
    ]
