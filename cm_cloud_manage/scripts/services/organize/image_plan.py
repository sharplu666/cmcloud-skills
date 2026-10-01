#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""organize plan 的 image 流程（``--target album|memory``，整理到相册/回忆故事）。

自相册整理编排移植（错误类换 ``OperationServiceError``、回执换
operation 的 ``ok_meta`` 风格 event ``organize_plan``）。管道：打开会话按 ``--from``
分流读入（refine 子集复用 per-row bucket 标签、flat 子集按 plan 参数重聚类、跳过
isFull 全量保障；search.jsonl 的部分快照先过全量保障续拉，让出原样上抛——main.py
已兜底）→ **非图片剔除（album|memory 仅收图片，category≠image 不进后续管道，回执
说明过滤数）** → 聚类拍平成单层 ``A_B`` 拼名（不分桶 = 单桶 ``''``）并冻结桶编号 →
未知占比统计 → ``--unknown`` / ``--only`` 用户选桶过滤（only 是用户选择、优先级最
高，编号冻结后执行）→ ``--merge-into`` 合并成单池（2026-09-02 定案：先合并后过门，
merge-into 恒等于「一个池、一次全集精选」，与不分桶路径同语义）→ 质量门（memory
恒走公共库 ``refine_for_memory`` 完整精选，仅对存活桶——统计与 ensure 都锚定本次
实际产物；每桶 top-50、merge 后单池即全集 top-50，固定流程无参数；album 无门，
图片全量进册——精选/去重走 refine 子集承接）→ 空桶名兜底（O17）→ 写 plan.jsonl
（``organizeType=image``，target/taskType 进 header，submit 从 header 读）→
预览回执 + ``next.submit`` 完整命令。

drive 流程不在本模块（``steps.plan`` 主流程，``--target drive`` 行为零变化）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from xml.sax.saxutils import escape

from utils.config import (
    IMAGE_NON_IMAGE_FILTER_NOTE,
    MEMORY_PHOTO_GATE_HINT,
    MEMORY_REFINE_NOTE,
    USE_SELECT_PHOTO,
)
from mclaw.api.search_fusion import File
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.organize.bucket.unknown_labels import (
    is_unknown_bucket_key,
    sort_bucket_keys,
    unknown_bucket_file_count,
)
from mclaw.shared.organize.cluster_ops import flatten_tree, run_cluster
from mclaw.shared.organize.dedup import (
    MEMORY_TOP_DEFAULT,
    MemoryRefineStats,
    refine_for_memory,
)
# 复用 transforms 的 _is_image（refine steps 同款：跨模块 import 私有符号先例）
from mclaw.shared.organize.transforms import _is_image
from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)
from mclaw.shared.organize.photo_organize_task import (
    TASK_TYPE_ALBUM,
    TASK_TYPE_MEMORY,
)
from services.errors import OperationServiceError
from services.organize.plan_common import (
    PlanInput,
    multi_label_overlap_note,
    read_plan_input,
    submit_cmd_text,
    with_select_then_plan,
)
from services.stdout_receipt import Handle, NeedsConfirmation, emit_handle, ok_meta

if TYPE_CHECKING:
    from cli.organize import OrganizePlanTask  # noqa: F401 仅供类型注解（运行期零依赖）

__all__ = ['run_image_plan']

#: target → task_type（album=2 / memory=3，写进 plan header，submit 读）
_TASK_TYPE = {'album': TASK_TYPE_ALBUM, 'memory': TASK_TYPE_MEMORY}
#: target → 中文标签（回执透出，便于 agent 口头汇报）
_TARGET_LABEL = {'album': '相册', 'memory': '回忆故事'}


# ──────────────────────────── plan 落盘结构（dict 只在写盘边界出现）────────────


@dataclass(frozen=True)
class ImagePlanRow:
    """一行整理项：fileId → 相册/回忆故事（targetName = 桶名 = 册名）。"""

    file_id: str
    bucket: str
    target_name: str
    name: str
    index: int

    def to_dict(self) -> dict[str, Any]:
        """plan.jsonl row 行形状（键序固定）。"""
        return {
            'fileId': self.file_id,
            'bucket': self.bucket,
            'targetName': self.target_name,
            'name': self.name,
            'index': self.index,
        }


@dataclass(frozen=True)
class ImagePlanHeader:
    """plan.jsonl 首行 header（公共库约定补 planHash，键序即写盘键序）。"""

    target: str
    task_type: int
    name: str
    cluster_args: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            'organizeType': 'image',
            'target': self.target,
            'taskType': self.task_type,
            'name': self.name,
            'cluster_args': self.cluster_args,
        }


# ──────────────────────────── image plan 编排 ────────────────────────────


def run_image_plan(task: 'OrganizePlanTask') -> None:
    """``--target album|memory`` 的 plan 管道（steps.plan 分支路由至此）。"""
    # 1) 打开会话按 --from 指向的文件分流读入：refine 子集（select/dedup.jsonl，
    #    复用 per-row bucket 标签、跳过 isFull 全量保障）或原始 search.jsonl
    #    （isFull=false 先过全量保障续拉补全，让出原样上抛——main.py 已兜底）。
    #    分流逻辑与 refine plan 共用 plan_common.read_plan_input（R2 合并）。
    try:
        session = OrganizeSession.open(task.from_handle)
    except OrganizeSessionError as exc:
        raise OperationServiceError(str(exc)) from exc
    plan_input: PlanInput = read_plan_input(task, session)
    files = plan_input.files
    subset_rows = plan_input.subset_rows
    header_in = plan_input.header
    is_subset = plan_input.is_subset

    # 1.5) album|memory 是图片能力：语料中的非图片（category≠image，如视频/文档）
    #      一律剔除，不进聚类/未知占比/质量门/plan（refine select/dedup 同款口径）；
    #      drive 不经本模块（全格式）。全剔空 → 明确报错（而非聚类为空的误导文案）。
    non_image_removed = len(files) - sum(1 for f in files if _is_image(f))
    if non_image_removed:
        files = [f for f in files if _is_image(f)]
        if subset_rows is not None:
            subset_rows = [(bk, f) for bk, f in subset_rows if _is_image(f)]
    if not files:
        raise OperationServiceError(
            f'语料中没有图片（{_TARGET_LABEL[task.target]}仅支持图片）；'
            '请换图片语料或检查搜索条件'
        )

    # 2) 聚类：带 bucket 标签的子集直接按标签分组（标签在 refine 时已定，
    #    hierarchical 已降维成 A_B 拼名，不重聚类）；flat 子集 / search.jsonl 按
    #    plan 参数聚类（mode 空 = 不分桶：所有文件单桶 ''，桶名即空串=整体一册；
    #    hierarchical 默认返回 tree，plan 需单层拼名，flatten_tree 拍平 A_B）。
    flat: dict[str, list[File]]
    if subset_rows is not None and any(bk for bk, _ in subset_rows):
        flat = {}
        for bk, f in subset_rows:
            flat.setdefault(bk, []).append(f)
    else:
        if not task.mode:
            flat = {'': list(files)}
        else:
            try:
                flat_raw, tree = run_cluster(
                    files,
                    mode=task.mode,
                    bucket=task.bucket,
                    buckets=list(task.buckets),
                )
            except ValueError as exc:
                raise OperationServiceError(f'参数错误：聚类失败：{exc}') from exc
            flat = (
                flatten_tree(tree)
                if flat_raw is None and tree is not None
                else dict(flat_raw or {})
            )
    # 2.4) 过滤无 fileId 的异常文件（正常服务端不会返回，无法执行整理动作，剔除）
    flat = {
        key: [f for f in fs if str(getattr(f, 'file_id', '') or '').strip()]
        for key, fs in flat.items()
    }
    flat = {k: v for k, v in flat.items() if v}
    if not flat:
        raise OperationServiceError('聚类结果为空；请检查 --bucket 维度参数')

    # 2.5) 冻结桶编号：聚类产物即分 idx，此后精选/过滤只删桶不重排——同输入同
    #      聚类参数下编号跨 target 一致，memory 精选清空的桶出占位行（§1 --only）
    idx_of: dict[str, int] = {
        key: i for i, key in enumerate(sort_bucket_keys(flat.keys()), 1)
    }

    # 2.6) 未知占比统计（聚类口径的质量信号，与 drive/recommend 同口径——在门与
    #      过滤之前统计；memory 门会剔无拍摄时间文件，门后统计会失真）。
    #      仅在用户未做选桶/未知处理时输出：--only / --unknown 已是用户的选择，
    #      占比信号失去服务对象，提示与 unknownRatio 键一并省略（2026-09-02 定案）
    unknown_count = unknown_bucket_file_count(flat)
    unknown_total = sum(len(v) for v in flat.values())
    unknown_ratio = (unknown_count / unknown_total) if unknown_total else 0.0
    ratio_visible = not task.only and task.unknown_action == 'keep'

    # 3) 用户选桶优先（--unknown → --only → 质量门）：编号冻结后先按用户意图砍桶，
    #    质量门只对存活桶执行——精选统计与产物同辖域，未选中桶不付相似图去重
    #    网络成本（only 是用户选择，优先级最高，2026-09-02 用户定案）
    # 3.1) --unknown：keep 透传 / drop 移除未知桶；idx_live = 存活桶的冻结编号
    buckets_filtered: dict[str, list[File]] = {}
    idx_live: dict[str, int] = {}
    for key in sort_bucket_keys(flat.keys()):
        if task.unknown_action == 'drop' and is_unknown_bucket_key(key):
            continue
        buckets_filtered.setdefault(key, []).extend(flat[key])
        idx_live[key] = idx_of[key]
    if not buckets_filtered:
        raise OperationServiceError(
            '聚类后无可用桶（全部为未知且 --unknown drop）；请调整维度或改 --unknown keep'
        )

    # 3.2) --only：按冻结编号只保留命中桶（编号 = 预览展示编号，跨 target 稳定）；
    #      merge+only 时捕获命中源桶与未命中编号（合并前口径），回执对照用
    only_sources: list[tuple[int, str, int]] = []
    only_missed: list[int] = []
    if task.only:
        wanted = {int(x) for x in task.only}
        if task.merge_into:
            valid = {idx_live[k] for k, v in buckets_filtered.items() if v}
            only_missed = sorted(wanted - valid)
        buckets_filtered = {
            k: v for k, v in buckets_filtered.items()
            if idx_live.get(k) in wanted and v
        }
        if not buckets_filtered:
            raise OperationServiceError(
                f'--only {",".join(str(x) for x in task.only)} 未命中任何桶；'
                '请检查 bucketId（取自上次 plan 回执 renderText 的 <bucketId>，'
                '编号聚类时冻结、跨 target 稳定），或换维度重新预览'
            )
        if task.merge_into:
            only_sources = sorted(
                (idx_live[k], k, len(v)) for k, v in buckets_filtered.items()
            )

    # 3.3) --merge-into：合并成单桶（合并成一个以该名称命名的相册/回忆故事，
    #      丢弃分组结构）。必须在质量门之前——memory 场景先合成一个池、门对全集
    #      精选一次（全局过滤/去重/top-50，2026-09-02 定案），与不分桶 merge 同
    #      语义；fileId 去重防同图多桶重复进册。
    if task.merge_into:
        merged_files: list[File] = []
        seen_ids: set[str] = set()
        for key in sort_bucket_keys(buckets_filtered.keys()):
            for f in buckets_filtered.get(key, []):
                fid = str(getattr(f, 'file_id', '') or '').strip()
                if fid and fid in seen_ids:
                    continue
                if fid:
                    seen_ids.add(fid)
                merged_files.append(f)
        buckets_filtered = {task.merge_into: merged_files} if merged_files else {}
        if not buckets_filtered:
            raise OperationServiceError(
                '--merge-into 合并后无保留文件；请检查搜索条件或 --only 编号'
            )

    # 3.4) 质量门（固定流程，无参数）：memory 恒走公共库 refine_for_memory 完整精选
    #    （filter→collapse_exact→dedup→ensure→top-50，仅对存活桶——merge-into 已先
    #    塌成单池时即全集一次精选；ensure 辖域与精选统计都锚定本次实际产物，整批
    #    ensure 不足抛 ValueError 在此转译）——门是固定校验而非可调精选，对已精选
    #    子集幂等；album 无门，全量进册（精选/去重诉求先 refine 产子集承接）。
    #    存活桶被门清空记入 emptied（merge 后单池全清走整单报错，不进此分支）：
    #    --only 命中直接报错（含桶名，不得静默改选别的桶），未 --only 出占位行
    #    （编号不回收）。
    refine_stats: Optional[MemoryRefineStats] = None
    emptied_by_refine: set[str] = set()
    if task.target == 'memory':
        try:
            refined, refine_stats = refine_for_memory(
                buckets_filtered, get_cloud_dispatcher(),
                use_select_photo=USE_SELECT_PHOTO,
            )
        except ValueError as exc:
            # 去重+精选后整批零存活 = 正常收束（2026-09-14 用户定案）：改 ok 回执
            # ——不产 error 壳/failedApi/failapi、不产 plan/卡/handle；尾部门规则
            # 说明句（两条路径均真实，不断言死因）。refine_for_memory 的 ValueError
            # 仅在零存活时抛（ensure「无合适的入选照片」/ AI 选图「精选后无可用
            # 照片」），无需按消息区分。
            ok_meta(
                'organize_plan',
                say_to_user=(
                    f'回忆故事精选失败：{exc}；请调整搜索条件或聚类维度。'
                    f'{MEMORY_PHOTO_GATE_HINT}'
                ),
                data={'fileCount': 0},
            )
            return
        emptied_by_refine = {k for k in buckets_filtered if k not in refined}
        if task.only and emptied_by_refine:
            hit_key = min(emptied_by_refine, key=lambda k: idx_live[k])
            raise OperationServiceError(
                f'--only {idx_live[hit_key]} 对应桶「{hit_key}」精选后为空；'
                '请换编号（其余桶编号不变），或调整搜索条件'
            )
        buckets_filtered = refined

    # 3.5) 防御性兜底（O17）：CLI 校验看不到聚类产物；空桶名=空相册/回忆故事名，
    #      必须在 merge-into 改名之后、rows 构建之前拦截，不能拖到 submit 才炸。
    if any(not str(k).strip() for k in buckets_filtered):
        raise OperationServiceError(
            '不分桶整理成相册/回忆故事需要名称：请加 --merge-into <名>，或用 --bucket <维度> 分桶'
        )

    # 4) 构造 plan rows + 预览文案（targetName = 桶名 = 相册/故事名）。非 merge
    #    预览行按冻结编号升序：精选清空的桶出占位行（--only 命中清空桶已在 3.4
    #    拦截，占位行只服务全量预览）。merge 后单桶不占编号（idx=0 仅作哨兵）：
    #    bucketId 只服务 --only 选桶、恒指冻结聚类桶，重计 1 会改写「1=原 1 号
    #    桶」映射（2026-09-03 用户定案：任何参数组合不改写编号映射）。merge+only
    #    时列命中源桶（冻结编号/桶名/数目）+ 合并目标行，供对照 only 是否生效；
    #    merge 无 only 维持裸合并行（2026-09-03 修订）
    if task.merge_into:
        entries: list[tuple[int, str, Optional[list[File]]]] = [
            (0, task.merge_into, next(iter(buckets_filtered.values())))
        ]
    else:
        entries = sorted(
            ((idx_live[k], k, v) for k, v in buckets_filtered.items() if v),
            key=lambda e: e[0],
        )
        entries += [(idx_live[k], k, None) for k in emptied_by_refine]
        entries.sort(key=lambda e: e[0])
    rows: list[ImagePlanRow] = []
    preview_lines: list[str] = []
    bucket_count = 0
    for bucket_idx, bucket_name, bucket_files in entries:
        if not bucket_files:
            preview_lines.append(f'{bucket_idx}. {bucket_name}：精选后为空')
            continue
        bucket_count += 1
        if bucket_idx:
            preview_lines.append(
                f'<bucketId>{bucket_idx}</bucketId> <bucketName>{escape(bucket_name)}</bucketName>：{len(bucket_files)} 张'
            )
        elif only_sources:
            for src_idx, src_name, src_count in only_sources:
                preview_lines.append(
                    f'<bucketId>{src_idx}</bucketId> <bucketName>{escape(src_name or "(根目录)")}</bucketName>：{src_count} 张'
                )
            preview_lines.append(
                f'合并到「{escape(task.merge_into)}」：{len(bucket_files)} 张'
            )
        else:
            preview_lines.append(f'{escape(bucket_name)}：{len(bucket_files)} 张')
        for index, f in enumerate(bucket_files, start=1):
            rows.append(ImagePlanRow(
                file_id=str(getattr(f, 'file_id', '') or '').strip(),
                bucket=bucket_name,
                target_name=bucket_name,
                name=str(getattr(f, 'name', '') or ''),
                index=index,
            ))

    # 5) 写 plan.jsonl（公共库原子写 <handle>/plan.jsonl）
    target_label = _TARGET_LABEL[task.target]
    header = ImagePlanHeader(
        target=task.target,
        task_type=_TASK_TYPE[task.target],
        name=f'整理到{target_label}',
        cluster_args={
            'mode': task.mode,
            'bucket': task.bucket,
            'buckets': list(task.buckets),
            'unknown_action': task.unknown_action,
            'refineKind': str(header_in.get('refineKind') or '') if is_subset else '',
            'only': list(task.only),
            'merge_into': task.merge_into,
        },
    )
    try:
        session.write_plan(header.to_dict(), [row.to_dict() for row in rows])
    except OrganizeSessionError as exc:
        raise OperationServiceError(
            f'写 plan 文件失败：{exc}；请停止并交用户决策'
        ) from exc

    # 6) 回执（preview + plan 合一）：精选统计 / 未知占比提示 / merge-into 说明进
    #    sayToUser；next.submit 带完整命令。精选括号 = 用户向流程说明（模板集中
    #    config.py，2026-09-03 用户定案）：损失数 + 规则一句说完，总数由开头
    #    「共 N 张」承载不重复报
    refine_note = ''
    if refine_stats is not None and (refine_stats.removed_total or refine_stats.picked):
        refine_note = (
            MEMORY_REFINE_NOTE
            .replace('<filtered>', str(refine_stats.label_filtered + refine_stats.taken_at_filtered))
            .replace('<deduped>', str(refine_stats.dedup_exact_removed + refine_stats.dedup_similar_removed))
            .replace('<label>', target_label)
            .replace('<top>', str(MEMORY_TOP_DEFAULT))
        )
    # merge+only 首行后加命中标注（源桶行紧随其后）；无未命中省略括号尾注
    only_mark = ''
    if only_sources:
        only_mark = '--only 命中编号 ' + ','.join(str(i) for i, _, _ in only_sources)
        if only_missed:
            only_mark += '（未命中 ' + ','.join(str(i) for i in only_missed) + '）'
        only_mark += '：'
    render_text = (
        f'整理方案预览（共 {len(rows)} 张，{bucket_count} 个桶，目标={target_label}）：\n'
        + (f'{only_mark}\n' if only_mark else '')
        + '\n'.join(preview_lines)
        + (f'\n{refine_note}' if refine_note else '')
    )
    say = (
        f'已生成{target_label}整理方案（共 {len(rows)} 张、{bucket_count} 个{target_label}）'
        f'{refine_note}，确认后我提交'
    )
    if non_image_removed > 0:
        say += (
            IMAGE_NON_IMAGE_FILTER_NOTE
            .replace('<label>', target_label)
            .replace('<kept>', str(len(rows)))
            .replace('<removed>', str(non_image_removed))
        )
    if is_subset:
        say += f'；本方案基于 refine 子集（{header_in.get("refineKind")}）'
    if unknown_count > 0 and ratio_visible:
        say += (
            f'；提示：未知维度桶占比 {unknown_ratio:.1%}（{unknown_count}/{unknown_total}）'
            '，可换维度，或用 --unknown drop 处理'
        )
    say += multi_label_overlap_note(
        task=task, header=header_in,
        total=len(rows), distinct=len({r.file_id for r in rows}), image=True,
    )
    if task.merge_into:
        say += f'；已合并到{target_label}「{task.merge_into}」（丢弃分组结构）'

    plan_rel = f'{session.id}/plan.jsonl'
    # name 与 target/taskType 同义、handle 与 handle 行同值，均不进 data（2026-09-02 瘦身）
    data: dict[str, Any] = {
        'renderText': render_text,
        'target': task.target,
        'taskType': _TASK_TYPE[task.target],
        'fileCount': len(rows),
        'bucketCount': bucket_count,
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

    submit_cmd = submit_cmd_text(plan_rel)
    next_steps: dict[str, str] = {
        'confirm-then-submit': f'等待用户确认整理方案后执行：{submit_cmd}',
    }
    next_steps = with_select_then_plan(next_steps, task, bucket_count=bucket_count)
    ok_meta(
        'organize_plan',
        say_to_user=say,
        # 二次确认：等用户确认方案后才执行 submit，禁止自动提交
        next_steps=next_steps,
        data=data,
        needs_confirmation=NeedsConfirmation(
            reason='整理方案已生成，提交前需用户确认',
            say_to_user='方案已生成，请确认后我再提交',
        ),
    )
    # handle 行收尾（协议行放 stdout 尾部，防 openclaw exec 头部截断）
    emit_handle(Handle(id=plan_rel, params={
        'step': 'plan',
        'target': task.target,
        'mode': task.mode,
        'bucket': task.bucket,
    }))
