#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""organize plan 管道共用段（函数级）：读入分流 / 叶构造 / 叶过滤链 / 回执命令模板。

三个 plan 管道（drive=steps.py、recommend=direction_preview.py、
album|memory=image_plan.py）逐字相同的阶段收拢于此，管道各自保留差异化阶段
（渲染 / 落盘 / 回执组装）。叶构造 helpers 自 steps.py 迁入——direction_preview
原惰性 import 自 steps 的反向依赖就此消除。image 的 dict 形态过滤链
（emptied_by_refine 占位 / --only 命中清空桶报错 / O17 空桶名兜底）语义独异，
不上提。禁止 import steps / direction_preview / image_plan（防循环依赖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from mclaw.api.search_fusion import File
from mclaw.shared.organize.bucket.registry import get_bucket_class
from mclaw.shared.organize.bucket.unknown_labels import (
    is_unknown_bucket_key,
    sort_bucket_keys,
)
from mclaw.shared.organize.cluster_ops import run_cluster
from mclaw.shared.organize.organize_session import OrganizeSession
from services.errors import OperationServiceError, ensure_full_search_results
from services.refine.subset_io import (
    is_merged_header,
    is_subset_header,
    read_subset,
    read_subset_header,
)
from utils.config import (
    MULTI_LABEL_OVERLAP_NOTE_FILE,
    MULTI_LABEL_OVERLAP_NOTE_IMAGE,
)

if TYPE_CHECKING:
    from cli.organize import OrganizePlanTask  # noqa: F401 仅供类型注解

__all__ = [
    'PlanInput',
    'ONLY_MISS_HINT_DRIVE',
    'ONLY_MISS_HINT_PREVIEW',
    'read_plan_input',
    'build_leaves',
    'leaf_has_unknown',
    'unknown_stats_from_leaves',
    'multi_label_overlap_note',
    'number_leaves',
    'filter_numbered',
    'submit_cmd_text',
    'with_select_then_plan',
]

#: 命令模板用的 main.py 绝对路径（services/organize/ 下与 steps.py 同款层级）
_MAIN_PY = str(Path(__file__).resolve().parents[2] / 'main.py')

#: --only 未命中提示文案（drive 提示回执 bucketId 来源，recommend 提示编号规则；
#: 两管道侧重不同，不静默统一）
ONLY_MISS_HINT_DRIVE = (
    '请检查 bucketId（取自上次 plan 回执 renderText 的 <bucketId>，'
    '编号聚类时冻结、跨 target 稳定），或换维度重新预览'
)
ONLY_MISS_HINT_PREVIEW = (
    '请检查编号（聚类冻结编号，1 起、跨 target 稳定），或换维度重新预览'
)


# ──────────────────────────── 读入分流（三管道同口径）────────────────────────


@dataclass(frozen=True)
class PlanInput:
    """读入阶段产物：``--from`` 分流后的语料 / 子集。"""

    files: list[File]                                 # 展开文件（聚类入口）
    subset_rows: Optional[list[tuple[str, File]]]     # 带桶标签行（非子集 = None）
    header: dict[str, Any]                            # 输入 header（search 续拉后为刷新版）
    is_subset: bool


def read_plan_input(
    task: 'OrganizePlanTask', session: OrganizeSession
) -> PlanInput:
    """按 ``--from`` 分流读入：refine 子集复用 per-row bucket 标签（跳过全量
    保障）/ merged 终态语料校验（绝不续拉）/ search.jsonl 部分快照先续拉补全
    （让出原样上抛，重跑即续拉）。"""
    input_path = session.dir / task.input_file
    if not input_path.is_file():
        raise OperationServiceError(
            f'会话 {session.id} 没有 {task.input_file}；'
            + (
                '请先用 search 搜索（产 handle）。'
                if task.input_file == 'search.jsonl'
                else '请先用 refine --kind merge 生成（如 op_<6位编码>/merged.jsonl）。'
                if task.input_file == 'merged.jsonl'
                else f'请先用 refine --kind 生成 {task.input_file}（如 op_<6位编码>/{task.input_file}）。'
            )
        )

    header_in = read_subset_header(input_path)
    is_subset = is_subset_header(header_in)

    subset_rows: Optional[list[tuple[str, File]]] = None
    files: list[File] = []
    if is_subset:
        # 子集路径：复用其 per-row bucket 标签直接成叶，不再精选/续拉。
        subset_rows = read_subset(input_path)
        if not subset_rows:
            raise OperationServiceError(
                f'子集 {task.input_file} 无有效文件记录；请重新 refine'
            )
        files = [f for _, f in subset_rows]
    elif task.input_file == 'merged.jsonl':
        # 合并语料：终态（恒 isFull=true），异常 false 报错重建，绝不续拉。
        if not is_merged_header(header_in):
            raise OperationServiceError(
                f'{task.input_file} 不是合法的 merge 产物'
                '（header 缺 resultRole=merged 标记）；请重新 merge 生成。'
            )
        if not bool(header_in.get('isFull')):
            raise OperationServiceError(
                f'{task.input_file} 的 isFull≠true，属于异常产物；请重新 merge 重建。'
            )
        files = [f for _, f in read_subset(input_path)]
        if not files:
            raise OperationServiceError('合并语料无有效文件记录；请重新 merge')
    elif task.input_file != 'search.jsonl':
        raise OperationServiceError(
            '--from 只支持 search.jsonl / merged.jsonl / select.jsonl / dedup.jsonl'
            '（refine 子集须带 refineKind 标记）；'
            f'当前传的是 {task.input_file}，不是合法的 refine 子集。'
        )
    else:
        if not bool(header_in.get('isFull')):
            header_in = ensure_full_search_results(str(input_path))
        files = list(session.read_search())
        if not files:
            raise OperationServiceError(
                '搜索结果无有效文件记录；请先用 search 搜索并落盘'
            )
    return PlanInput(
        files=files, subset_rows=subset_rows,
        header=header_in, is_subset=is_subset,
    )


# ──────────────────────────── 叶子构造（原始搜索聚类 / 子集 bucket 复用）────────


def _collect_tree_leaves(
    node: Any, prefix: list[str], leaves: list[tuple[list[str], list[File]]]
) -> None:
    """递归把 hierarchical 树收成 ``[(路径段, [File]), ...]``。

    dict 下钻、非空 list 收为叶；按 ``sort_bucket_keys`` 定「普通桶升序 + 未知末尾」。
    """
    if isinstance(node, list):
        if node:
            leaves.append((list(prefix), [f for f in node if f is not None]))
    elif isinstance(node, dict):
        for key in sort_bucket_keys(node.keys()):
            _collect_tree_leaves(node[key], prefix + [str(key)], leaves)


def _bucketed_to_leaves(
    bucketed: list[tuple[str, File]],
) -> list[tuple[list[str], list[File]]]:
    """子集 ``[(bucket, File), ...]`` → 叶子 ``[(segs, [File]), ...]``，保留首次出现顺序。

    bucket 非空 → ``segs=[bucket]``；空串 → ``segs=[]``（等价不分桶单叶）。
    桶顺序经 ``sort_bucket_keys``（普通升序 + 未知末尾）。
    """
    groups: dict[str, list[File]] = {}
    order: list[str] = []
    for bk, f in bucketed:
        if bk not in groups:
            groups[bk] = []
            order.append(bk)
        groups[bk].append(f)
    ordered = sort_bucket_keys(order)
    return [
        (([bk] if bk else []), groups[bk])
        for bk in ordered
        if groups[bk]
    ]


def _cluster_to_leaves(
    task: 'OrganizePlanTask', files: list[File]
) -> list[tuple[list[str], list[File]]]:
    """原始搜索 ``List[File]`` → 聚类 → 叶子 ``[(segs, [File]), ...]``。

    mode 空 = 不分桶：所有文件单桶 ``''``；single/cross 取 flat 单层；
    hierarchical 递归取叶（路径段 = 各级 key，多层目录）。
    """
    no_bucket = not task.mode
    if no_bucket:
        single = list(files)
        return [([], single)] if single else []
    try:
        flat, tree = run_cluster(
            files,
            mode=task.mode,
            bucket=task.bucket,
            buckets=list(task.buckets),
        )
    except ValueError as exc:
        raise OperationServiceError(f'参数错误：聚类失败：{exc}') from exc

    leaves: list[tuple[list[str], list[File]]] = []
    if tree is not None:
        _collect_tree_leaves(tree, [], leaves)
    elif flat:
        for key in sort_bucket_keys(flat.keys()):
            bucket_files = list(flat[key])
            if bucket_files:
                leaves.append(([key], bucket_files))
    return leaves


def build_leaves(
    task: 'OrganizePlanTask', inp: PlanInput
) -> list[tuple[list[str], list[File]]]:
    """子集带 bucket 标签 → 复用标签直接成叶（不聚类）；flat 子集 / 语料 →
    按 plan 参数聚类成叶。聚类结果为空报参数错误。"""
    leaves: list[tuple[list[str], list[File]]]
    if inp.is_subset:
        if any(bk for bk, _ in inp.subset_rows or []):
            # per-bucket refine 子集：每行带 bucket 标签 → 直接成叶，不聚类。
            leaves = _bucketed_to_leaves(inp.subset_rows or [])
        else:
            # flat refine 子集（bucket 全空）→ 用 plan 自己的 --bucket 重新聚类。
            leaves = _cluster_to_leaves(task, inp.files)
    else:
        leaves = _cluster_to_leaves(task, inp.files)
    if not leaves:
        raise OperationServiceError('聚类结果为空；请检查 --bucket 维度参数')
    return leaves


# ──────────────────────────── 未知统计 + 叶过滤链（drive/recommend 共用）────────


def leaf_has_unknown(segs: list[str]) -> bool:
    # cross 的 key 可能是 'a_b' 拼名，整段未知判定；hierarchical 各段独立判
    return any(is_unknown_bucket_key(s) for s in segs)


def unknown_stats_from_leaves(
    leaves: list[tuple[list[str], list[File]]]
) -> tuple[int, int, float]:
    """过滤前口径的未知占比（聚类质量信号：drop/merge 后仍如实提示维度缺值
    程度，不静默丢信息）。返回 (未知文件数, 有 id 文件总数, 占比)。"""
    unknown_ids: set[str] = set()
    all_ids: set[str] = set()
    for segs, leaf_files in leaves:
        leaf_unknown = leaf_has_unknown(segs)
        for f in leaf_files:
            fid = str(getattr(f, 'file_id', '') or '').strip()
            if not fid:
                continue
            all_ids.add(fid)
            if leaf_unknown:
                unknown_ids.add(fid)
    unknown_count = len(unknown_ids)
    total = len(all_ids)
    ratio = (unknown_count / total) if total else 0.0
    return unknown_count, total, ratio


def multi_label_overlap_note(
    *,
    task: 'OrganizePlanTask',
    header: dict[str, Any],
    total: int,
    distinct: int,
    image: bool = False,
) -> str:
    """多标签分桶计数提示句（含前导「；」，``image=True`` 用图片措辞）。

    双条件触发，缺一返回空串：聚类维度含多值桶（注册表 ``is_multi_value``，
    如 thingLabelList/peopleNameList；子集路径 plan 侧无维度参数 → 读 header
    的 ``refineClusterArgs``——refine 聚类参数快照）；且各桶计数相加
    （``total``）大于去重文件数（``distinct``）。未注册维度名不视作多值。"""
    dims = list(task.buckets) or ([task.bucket] if task.bucket else [])
    if not dims and header:
        refine_args = header.get('refineClusterArgs') or {}
        dims = (
            list(refine_args.get('buckets') or [])
            or ([refine_args.get('bucket')] if refine_args.get('bucket') else [])
        )
    multi = False
    for dim in dims:
        if not str(dim or '').strip():
            continue
        try:
            if get_bucket_class(str(dim).strip()).is_multi_value:
                multi = True
                break
        except ValueError:
            continue
    if not multi or distinct >= total:
        return ''
    template = (
        MULTI_LABEL_OVERLAP_NOTE_IMAGE if image else MULTI_LABEL_OVERLAP_NOTE_FILE
    )
    return (
        template
        .replace('<total>', str(total))
        .replace('<distinct>', str(distinct))
    )


def number_leaves(
    leaves: list[tuple[list[str], list[File]]]
) -> list[tuple[int, list[str], list[File]]]:
    """冻结桶编号：聚类产物即分 idx，此后过滤只删桶不重排（同输入同聚类参数下
    编号跨 target 一致）。"""
    return [
        (i, segs, leaf_files) for i, (segs, leaf_files) in enumerate(leaves, 1)
    ]


def filter_numbered(
    task: 'OrganizePlanTask',
    numbered: list[tuple[int, list[str], list[File]]],
    only_miss_hint: str,
) -> tuple[
    list[tuple[int, list[str], list[File]]],
    list[tuple[int, list[str], int]],
    list[int],
]:
    """``--unknown`` → ``--only`` → ``--merge-into`` 逐层过滤（只删桶不重排）；
    ``only_miss_hint`` 为 ``--only`` 未命中的后续提示文案（两管道侧重不同）。
    返回 (过滤合并后的桶, only 命中源桶, only 未命中编号)——后两项仅在
    ``--only`` 与 ``--merge-into`` 同用时非空，供回执列命中源桶对照。"""
    only_sources: list[tuple[int, list[str], int]] = []
    only_missed: list[int] = []
    if task.unknown_action == 'drop':
        numbered = [
            (i, segs, list(leaf_files))
            for i, segs, leaf_files in numbered
            if not leaf_has_unknown(segs)
        ]
    if not numbered:
        raise OperationServiceError(
            '聚类后无可用桶（全部为未知且 --unknown drop）；请调整维度或改 --unknown keep'
        )

    if task.only:
        wanted = {int(x) for x in task.only}
        if task.merge_into:
            only_missed = sorted(wanted - {entry[0] for entry in numbered})
        numbered = [entry for entry in numbered if entry[0] in wanted]
        if not numbered:
            raise OperationServiceError(
                f'--only {",".join(str(x) for x in task.only)} 未命中任何桶；'
                f'{only_miss_hint}'
            )
        if task.merge_into:
            only_sources = [
                (i, segs, len(fs)) for i, segs, fs in numbered
            ]

    if task.merge_into:
        merged_files: list[File] = []
        seen_ids: set[str] = set()
        for _i, _segs, leaf_files in numbered:
            for f in leaf_files:
                fid = str(getattr(f, 'file_id', '') or '').strip()
                if fid and fid in seen_ids:
                    continue
                if fid:
                    seen_ids.add(fid)
                merged_files.append(f)
        numbered = [(1, [task.merge_into], merged_files)] if merged_files else []
        if not numbered:
            raise OperationServiceError(
                '--merge-into 合并后无保留文件；请检查搜索条件或 --only 编号'
            )
    return numbered, only_sources, only_missed


# ──────────────────────────── 回执命令模板（drive/image 共用）─────────────────


def submit_cmd_text(plan_rel: str) -> str:
    """回执 nextSteps 的 submit 完整命令模板。"""
    return (
        f'python3 {_MAIN_PY} organize --step submit '
        f'--from {plan_rel} --processing-hint "<简洁整理任务名>"'
    )


def with_select_then_plan(
    next_steps: dict[str, str],
    task: 'OrganizePlanTask',
    *,
    bucket_count: int,
) -> dict[str, str]:
    """bucket_count>1 且有分桶维度时追加「部分桶复用」指引命令（返回新 dict）。
    模板须回显完整聚类参数才能复现冻结编号（--only 编号跨 target 稳定）。"""
    if not (bucket_count > 1 and (task.bucket or task.buckets)):
        return next_steps
    # 部分桶复用：--only 编号聚类时冻结，模板须回显完整聚类参数才能复现编号
    mode_flag = (
        f'--mode {task.mode} ' if task.mode and task.mode != 'single' else ''
    )
    bucket_flag = (
        f'--bucket {",".join(task.buckets)}'
        if task.buckets else f'--bucket {task.bucket}'
    )
    return {
        **next_steps,
        'select-then-plan': (
            f'用户只要预览中部分桶时执行（--only 可传多份）：'
            f'python3 {_MAIN_PY} organize --step plan '
            f'--from {task.from_handle}/{task.input_file} '
            f'--target {task.target} '
            f'{mode_flag}{bucket_flag} '
            f'--only <bucketId1>,...,<bucketIdN>'
        ),
    }
