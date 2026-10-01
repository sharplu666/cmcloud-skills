#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``--target recommend`` 的 plan 管道（整理方向推荐，仅预览不落盘）。

聚类分桶（或复用 refine 子集标签）→ ``--unknown`` / ``--only`` / ``--merge-into``
过滤 → 三情形推荐回执（情形 1 回忆故事 / 情形 2 相册 / 情形 3 子目录）+ 三条带
具体 ``--target`` 的重跑命令。零写副作用：不写 plan.jsonl、不解析/创建整理根
目录、不跑 memory 质量门、不需要会话环境——submit 只认 plan.jsonl header，
recommend 从不落盘，天然隔离。无数据驱动推荐：三案并列，由用户选定。

叶子构造（``_cluster_to_leaves`` / ``_bucketed_to_leaves``）等共用段 import 自
plan_common（单向；原惰性 import 自 steps 的反向依赖已消除）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)
from mclaw.shared.organize.transforms import _is_image
from services.errors import OperationServiceError
from services.organize.plan_common import (
    ONLY_MISS_HINT_PREVIEW,
    build_leaves,
    filter_numbered,
    multi_label_overlap_note,
    number_leaves,
    read_plan_input,
    unknown_stats_from_leaves,
)
from services.stdout_receipt import Handle, NeedsConfirmation, emit_handle, ok_meta

if TYPE_CHECKING:
    from cli.organize import OrganizePlanTask  # noqa: F401 仅供类型注解

__all__ = ['run_direction_preview']

#: 重跑命令模板用的 main.py 绝对路径（services/organize/ 下与 steps.py 同款层级）
_MAIN_PY = str(Path(__file__).resolve().parents[2] / 'main.py')

#: 归类分布最多展示的桶数（超出折叠成一行）
_DIST_PREVIEW_MAX = 10


def run_direction_preview(task: 'OrganizePlanTask') -> None:
    """三情形方向推荐：读入 → 过滤 → 推荐回执；不落盘不触会话（全量保障除外）。"""
    # 1) 打开会话；读入分流（refine 子集 / merged / search 续拉）与叶构造共用
    #    plan_common（三管道同口径）——推荐必须基于全量，否则会把「没拉到的」
    #    当「不存在的」给错建议；让出原样上抛，重跑仍 recommend。
    try:
        session = OrganizeSession.open(task.from_handle)
    except OrganizeSessionError as exc:
        raise OperationServiceError(str(exc)) from exc

    inp = read_plan_input(task, session)
    leaves = build_leaves(task, inp)
    header_in = inp.header
    is_subset = inp.is_subset

    # 2) 未知占比统计（聚类口径的质量信号，过滤前统计，与 drive/image 管道一致）。
    #    仅在用户未做选桶/未知处理时输出：--only / --unknown 已是用户的选择，
    #    占比信号失去服务对象，提示与 unknownRatio 键一并省略（2026-09-02 定案）
    unknown_count, id_total, unknown_ratio = unknown_stats_from_leaves(leaves)
    ratio_visible = not task.only and task.unknown_action == 'keep'

    # 3) 冻结桶编号 + --unknown / --only / --merge-into 过滤链（与 drive 管道
    #    同款语义：聚类产物即分 idx，过滤只删桶不重排，跨 target 一致）
    # merge/only 命中明细不进推荐回执（推荐无合并预览行，桶行本就带编号）
    numbered, _, _ = filter_numbered(
        task, number_leaves(leaves), ONLY_MISS_HINT_PREVIEW
    )

    # 4) 产物统计：总数 / 每桶图片数（未知占比已在过滤前算好，见 #2）。
    #    情形 1/2（memory/album）是图片能力：计数用图片数、0 图桶不列（无法成册），
    #    头部册数 = 有图桶数；情形 3（drive）全行数、全桶列出。
    bucket_count = len(numbered)
    total = sum(len(fs) for _, _, fs in numbered)
    image_total = 0
    leaf_stats: list[tuple[int, str, str, int, int]] = []   # (桶编号, drive 名, 册名, 全行数, 图片数)
    for idx, segs, leaf_files in numbered:
        drive_name = '/'.join(segs)
        album_name = '_'.join(segs)
        n_img = sum(1 for f in leaf_files if _is_image(f))
        image_total += n_img
        leaf_stats.append((idx, drive_name, album_name, len(leaf_files), n_img))
    img_buckets = [s for s in leaf_stats if s[4] > 0]
    img_bucket_count = len(img_buckets)
    needs_name = any(not album_name for _, _, album_name, _, _ in leaf_stats)

    def _scenario_bucket_line(bucket_idx: int, name: str, label: str, tail: str) -> str:
        """情形桶行：带 ``<bucketId>/<bucketName>`` 标签（同 image_plan 预览行；
        编号聚类时冻结、跨 target 一致，供 --only 引用）。merge-into 合并后的
        单桶不带编号（2026-09-03 定案），退回「」形态（label 空 = 情形 3 子目录行）。"""
        if task.merge_into:
            if label:
                return f'  - {label}「{name}」：{tail}'
            return f'  - {name}（{tail}）'
        return (
            f'  - <bucketId>{bucket_idx}</bucketId> '
            f'<bucketName>{escape(name)}</bucketName>：{tail}'
        )

    # 5) renderText：归类分布（前 10 桶折叠）+ 三情形并列（无图片隐藏情形 1/2）
    dim = ' + '.join(task.buckets) if task.buckets else (task.bucket or '')
    lines: list[str] = [
        f'搜索：「{str(header_in.get("query") or "") or "整理结果"}」',
        f'整理方向推荐（共 {total} 个文件，{bucket_count} 个桶，图片 {image_total} 张）',
        '',
        '📂 归类分布',
        f'按 {dim} 分为 {bucket_count} 类：' if dim else f'共 {bucket_count} 类（不分桶）：',
    ]
    shown = leaf_stats[:_DIST_PREVIEW_MAX]
    for _idx, drive_name, _album_name, n, _n_img in shown:
        lines.append(f'  {drive_name or "(根目录)"}：{n} 张')
    rest = leaf_stats[_DIST_PREVIEW_MAX:]
    if rest:
        lines.append(f'  其余 {len(rest)} 类合计：{sum(n for *_, n, _ in rest)} 张')

    lines.append('')
    if image_total > 0:
        lines.append('✨ 整理方案（请选情形 1/2/3，按对应命令带 --target 重跑 plan）')
        # 图片能力专门说明：album|memory 仅收图片（不分桶/分桶两分支同款一句话）
        lines.append('（相册 / 回忆故事仅支持图片，非图片文件不进情形 1/2；全部文件整理选情形 3）')
    else:
        lines.append('✨ 整理方案（无图片，仅目录整理可用，按对应命令带 --target drive 重跑 plan）')
    if image_total > 0:
        if needs_name:
            lines.append('情形 1：创建 1 个回忆故事（未分桶，重跑时用 --merge-into 命名）：')
            lines.append(f'  - 回忆故事（未命名）：去重前 {image_total} 张')
            lines.append('情形 2：创建 1 个相册（未分桶，重跑时用 --merge-into 命名）：')
            lines.append(f'  - 相册（未命名）：{image_total} 张')
        else:
            lines.append(
                f'情形 1：按 {dim} 创建 {img_bucket_count} 个回忆故事'
                '（回忆故事会对图片进行去重，超过 50 张时按图像质量评分截断）：'
            )
            for idx, _drive_name, album_name, _n, n_img in img_buckets:
                lines.append(_scenario_bucket_line(idx, album_name, '回忆故事', f'去重前 {n_img} 张'))
            lines.append(f'情形 2：按 {dim} 创建 {img_bucket_count} 个相册：')
            for idx, _drive_name, album_name, _n, n_img in img_buckets:
                lines.append(_scenario_bucket_line(idx, album_name, '相册', f'{n_img} 张'))
    if needs_name:
        lines.append('情形 3：全部文件收进「会话默认目录」（不分桶）：')
        lines.append(f'  - 会话默认目录（{total} 张）')
    else:
        lines.append(
            f'情形 3：在「会话默认目录」下按 {dim} 各建子目录'
            '（可用 --parent-path 指定其他目录）：'
        )
        for idx, drive_name, _album_name, n, _n_img in leaf_stats:
            lines.append(_scenario_bucket_line(idx, drive_name, '', f'{n} 张'))
    lines.append('')
    lines.append('（不满意可拒绝，不会执行任何改动）')
    render_text = '\n'.join(lines)

    # 6) 回执：say + data + 三条重跑命令（参数原样保留；未分桶需命名时
    #    album/memory 命令带 --merge-into 占位；无图片只剩 drive）
    if image_total > 0:
        say = (
            f'整理方向推荐已生成（共 {total} 个文件、{bucket_count} 个桶），请选情形 1/2/3'
        )
    else:
        say = (
            f'整理方向推荐已生成（共 {total} 个文件、{bucket_count} 个桶，无图片），'
            '仅支持情形 3（目录整理）'
        )
    if is_subset:
        say += f'；本推荐基于 refine 子集（{header_in.get("refineKind")}）'
    if unknown_count > 0 and ratio_visible:
        say += (
            f'；提示：未知维度桶占比 {unknown_ratio:.1%}（{unknown_count}/{id_total}）'
            '，可换维度，或用 --unknown drop 处理'
        )
    say += multi_label_overlap_note(
        task=task, header=header_in,
        total=total,
        distinct=len({
            str(getattr(f, 'file_id', '') or '').strip()
            for _, _, leaf_files in numbered
            for f in leaf_files
        }),
    )
    if task.merge_into:
        say += f'；已合并到「{task.merge_into}」'

    from_rel = f'{session.id}/{task.input_file}'
    # handle 与 handle 行同值，不进 data（2026-09-02 瘦身）
    data: dict[str, Any] = {
        'renderText': render_text,
        'target': 'recommend',
        'fileCount': total,
        'bucketCount': bucket_count,
        'imageCount': image_total,
        'source': 'subset' if is_subset else 'search',
    }
    if ratio_visible:
        data['unknownRatio'] = round(unknown_ratio, 4) if unknown_count else 0.0
    if is_subset:
        data['refineKind'] = header_in.get('refineKind')
    if task.only:
        data['only'] = list(task.only)
    if task.merge_into:
        data['mergeInto'] = task.merge_into

    base = f'python3 {_MAIN_PY} organize --step plan --from {from_rel}'
    if task.mode:
        base += f' --mode {task.mode}'
    if task.buckets:
        base += f" --bucket {','.join(task.buckets)}"
    elif task.bucket:
        base += f' --bucket {task.bucket}'
    if task.merge_into:
        base += f' --merge-into {task.merge_into}'
    if task.unknown_action == 'drop':
        base += ' --unknown drop'
    if task.only:
        base += f" --only {','.join(str(x) for x in task.only)}"

    next_steps: dict[str, str] = {'plan_drive': f'{base} --target drive'}
    if image_total > 0:
        name_suffix = ' --merge-into "<名称>"' if needs_name else ''
        next_steps['plan_album'] = f'{base} --target album{name_suffix}'
        next_steps['plan_memory'] = f'{base} --target memory{name_suffix}'

    ok_meta(
        'organize_plan',
        say_to_user=say,
        next_steps=next_steps,
        data=data,
        needs_confirmation=NeedsConfirmation(
            reason='方向推荐已生成，需用户选择整理去向',
            say_to_user='请选择整理去向，我再生成方案',
        ),
    )
    # handle 行收尾（协议行放 stdout 尾部，防 openclaw exec 头部截断）
    emit_handle(Handle(id=from_rel, params={
        'step': 'plan',
        'target': 'recommend',
        'mode': task.mode,
        'bucket': task.bucket,
    }))
