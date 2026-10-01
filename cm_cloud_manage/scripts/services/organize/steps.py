#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""organize 四阶段编排：``OrganizeService`` 一类管理 plan/submit/status/retry。

plan 管道（recommend 缺省 → ``direction_preview.py`` 三情形方向推荐，仅预览不落盘；
drive → 本文件；``--target album|memory`` → ``image_plan.py``）：打开会话读搜索结果
（部分快照先过全量保障续拉，避免把「没拉到的」当「不存在的」）→ 聚类分桶（或读
refine 子集复用其 bucket 标签直接成叶）→ 统一成叶子列表 → --unknown / --only /
--merge-into 逐层过滤 → resolve 整理根目录 → 写 plan.jsonl → 预览回执 + nextSteps。
读入分流 / 叶构造 / 叶过滤链 / 回执命令模板共用 ``plan_common.py``。
去重/精选已抽出为独立子命令 ``refine``——drive plan 不再做去重/精选，改为可读 refine
产出的子集（``--from <handle>/<file>.jsonl``），读子集时复用其 bucket 标签成叶、
不再精选/续拉；flat 子集（bucket 全空）则按 plan 的 ``--mode`` / ``--bucket`` 重新聚类。

plan 管道（``--target album|memory``，整理到相册/回忆故事）在 ``image_plan.py``，
plan() 开头分支路由；质量门（memory 完整精选 / album 逐桶去重精选）在彼处，本文件
drive 主流程不受影响。submit：读 ``<handle>/plan.jsonl`` → 从 header 读
organizeType/target/taskType 路由（image → task_type=2/3 + 相册文案；drive 固定
task_type=1 原行为）→ photoOrganize/task 提交（--dry-run 仅校验）→ taskId 回执 +
卡片。提交/重试响应带 taskInfo 即同步终态：say 直接汇报结果、next 不给 status 查询
命令，exit code 按终态分化（submit 同步 4/5 与 status 终态 4/5 → 2，retry 恒 0）；
异步与非终态保持等待话术。status：单次 query，计数仅终态输出（非终态只透状态、
不发卡，提示只进 sayToUser，终态才发卡）。
retry：发起重试（已成功则 skipped）；``--target`` 必填、仅客户端渲染用（taskList 卡
taskType/organizeType 与文案标签，HTTP 请求仍只带 taskId）。status/retry 文案按
task_type 映射目标标签（1 归档 / 2 相册 / 3 回忆故事）。卡片决策 /
原子写盘下放公共库 organize_cards / OrganizeSession；fire-and-forget，不内部轮询。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union
from xml.sax.saxutils import escape

from mclaw.api.base._ai_space_log import (
    append_ai_space_log_record,
    resolve_ai_space_log_path,
)
from mclaw.shared.cm_cloud.cloud_auth import mclaw_allowed_dir
from mclaw.shared.cm_cloud.folder_ops import (
    ensure_mclaw_dir_path,
)
from mclaw.shared.cm_cloud.session_cli_validate import extract_session_body
from mclaw.shared.organize.organize_cards import (
    ORGANIZE_TYPE_BY_TASK,
    build_task_submitted_summary,
    emit_card_for_snapshot,
    organize_task_name,
)
from mclaw.shared.organize.organize_session import (
    OrganizeSession,
    OrganizeSessionError,
)
from mclaw.shared.organize.photo_organize_task import (
    TASK_TYPE_ALBUM,
    TASK_TYPE_DRIVE,
    TASK_TYPE_MEMORY,
    OrganizeTaskClient,
    OrganizeTaskError,
)
from mclaw.shared.postprocess.paths import (
    CloudPathError,
    join_cloud_dir_path,
    normalize_cloud_dir_path,
    split_cloud_dir_path,
)
from services.organize.direction_preview import run_direction_preview
from services.organize.image_plan import run_image_plan
from services.organize.plan_common import (
    ONLY_MISS_HINT_DRIVE,
    build_leaves,
    filter_numbered,
    multi_label_overlap_note,
    number_leaves,
    read_plan_input,
    submit_cmd_text,
    unknown_stats_from_leaves,
    with_select_then_plan,
)
from session_folder import (
    SessionFolderError,
    ensure_default_session_upload_parent,
)
from utils.config import EXIT_BUSINESS_ERROR, EXIT_OK
from utils.organize_modes import render_rename_template
from mclaw.shared.cm_cloud.session_cli_validate import resolve_current_session
from services.errors import OperationServiceError
from services.stdout_receipt import Handle, NeedsConfirmation, emit_handle, ok_meta

if TYPE_CHECKING:
    from cli.organize import (  # noqa: F401 仅供类型注解（运行期零依赖）
        OrganizePlanTask,
        OrganizeSubmitTask,
        OrganizeTaskRef,
    )

    # run() 的 task 三态之一（按 step 对应）
    PlanTask = Union[OrganizePlanTask, OrganizeSubmitTask, OrganizeTaskRef]

__all__ = ['OrganizeService', 'PlanHeader', 'PlanRow']

#: nextSteps 命令模板用的 main.py 绝对路径（services/<pkg>/steps.py 的 parents[2] 即 scripts 目录）
_MAIN_PY = str(Path(__file__).resolve().parents[2] / 'main.py')

#: image 流程 target → 中文标签（submit/status/retry 文案透出；drive 无需标签）
_IMAGE_TARGET_LABEL = {TASK_TYPE_ALBUM: '相册', TASK_TYPE_MEMORY: '回忆故事'}
#: task_type → 中文标签（status/retry 查询结果按快照 task_type 映射；未知值兜底「整理」）
_TASK_TYPE_LABEL = {
    TASK_TYPE_DRIVE: '归档',
    TASK_TYPE_ALBUM: '相册',
    TASK_TYPE_MEMORY: '回忆故事',
}

#: retry --target → task_type（仅客户端渲染：taskList 卡与文案标签；HTTP 重试请求仍只带 taskId）
_RETRY_TARGET_TO_TASK_TYPE = {
    'drive': TASK_TYPE_DRIVE,
    'album': TASK_TYPE_ALBUM,
    'memory': TASK_TYPE_MEMORY,
}

#: task_type → retry --target token（status 终态 4/5 的 retry 指引命令拼参用）
_TASK_TYPE_TO_TARGET = {v: k for k, v in _RETRY_TARGET_TO_TASK_TYPE.items()}


def _task_label_prefix(task_type: Any) -> str:
    """task_type → say 文案前缀「{标签}整理任务」（1 归档 / 2 相册 / 3 回忆故事）。

    未知 task_type（快照缺字段/0）退回「整理任务」，不编造目标标签。
    """
    label = _TASK_TYPE_LABEL.get(int(task_type or 0), '')
    return f'{label}整理任务' if label else '整理任务'


def _terminal_say(snap: Any, tt: str) -> str:
    """终态结果文案（3 全部成功 / 4 全部失败含 errorMsg / 5 部分成功；兜底 status_text）。

    submit/retry 同步终态与 status 终态共用；下一步指引（retry 命令）由调用方按需给。
    """
    if snap.is_success:
        return (
            f'{tt}已完成（全部成功）：共 {snap.total_count} 个，'
            f'成功 {snap.success_count} 个'
        )
    if snap.status == 4:
        reason = f'（原因：{snap.error_msg}）' if snap.error_msg else ''
        return f'{tt}终态：全部失败（共 {snap.total_count} 个）{reason}'
    if snap.status == 5:
        return (
            f'{tt}终态：部分成功（共 {snap.total_count} 个，'
            f'成功 {snap.success_count} 个，失败 {snap.fail_count} 个）'
        )
    return f'{tt}终态：{snap.status_text}'


# ──────────────────────────── plan 落盘结构（dict 只在写盘边界出现）────────────


@dataclass(frozen=True)
class PlanRow:
    """一行整理项：fileId → 目标目录（+ 可选重命名）。"""

    file_id: str
    bucket: str
    name: str
    index: int
    target_path: str
    target_file_name: str = ''

    def to_dict(self) -> dict[str, Any]:
        """plan.jsonl row 行形状（键序固定；targetFileName 仅在有重命名时出现）。"""
        row: dict[str, Any] = {
            'fileId': self.file_id,
            'bucket': self.bucket,
            'name': self.name,
            'index': self.index,
            'targetPath': self.target_path,
        }
        if self.target_file_name:
            row['targetFileName'] = self.target_file_name
        return row


@dataclass(frozen=True)
class PlanHeader:
    """plan.jsonl 首行 header（公共库约定补 planHash，键序即写盘键序）。"""

    root_path: str
    root_file_id: str
    rename_template: str
    cluster_args: dict[str, Any]
    source: str   # 'search' | 'subset'：plan 的输入来源（原始搜索 or refine 子集）

    def to_dict(self) -> dict[str, Any]:
        return {
            'organizeType': 'file',
            'name': f'整理到 {self.root_path}',
            'rootDirPath': self.root_path,
            'rootFileId': self.root_file_id,
            'renameTemplate': self.rename_template,
            'cluster_args': self.cluster_args,
            'source': self.source,
        }


# ──────────────────────────── 四阶段编排 ────────────────────────────


class OrganizeService:
    """organize 四阶段编排：plan 规划 → submit 提交 → status 查询 / retry 重试。"""

    def run(self, step: str, task: PlanTask) -> int:
        """按已校验的 step 路由到同名方法并透传退出码（None → EXIT_OK）。"""
        exit_code = getattr(self, step)(task)
        return exit_code if isinstance(exit_code, int) else EXIT_OK

    # ── plan：搜索结果 / refine 子集 → 聚类或复用 bucket → plan.jsonl + 预览回执 ──

    def plan(self, task: OrganizePlanTask) -> None:
        # --target recommend（缺省）→ 方向推荐（仅预览不落盘，零写副作用，无需会话）；
        # album|memory → image 流程（整理到相册/回忆故事，含质量门）；
        # image 不需要会话目录（无根目录 resolve），故路由先于 resolve_current_session。
        if task.target == 'recommend':
            run_direction_preview(task)
            return
        if task.target != 'drive':
            run_image_plan(task)
            return

        session_str = resolve_current_session(required=True)

        # 1) 打开会话；读入分流（refine 子集 / merged / search 续拉）与叶构造
        #    共用 plan_common（三管道同口径），drive 差异化阶段留在本方法。
        try:
            session = OrganizeSession.open(task.from_handle)
        except OrganizeSessionError as exc:
            raise OperationServiceError(str(exc)) from exc

        inp = read_plan_input(task, session)
        leaves = build_leaves(task, inp)
        header_in = inp.header
        is_subset = inp.is_subset

        # 2) 未知占比统计（聚类口径的质量信号，过滤前统计）。仅在用户未做选桶/
        #    未知处理时输出：--only / --unknown 已是用户的选择，占比信号失去
        #    服务对象，提示与 unknownRatio 键一并省略（2026-09-02 定案）
        unknown_count, total, unknown_ratio = unknown_stats_from_leaves(leaves)
        ratio_visible = not task.only and task.unknown_action == 'keep'

        # 2.0-2.3) 冻结编号 + --unknown / --only / --merge-into 逐层过滤（共用
        #          plan_common；编号聚类时冻结、过滤只删桶不重排，同输入同聚类
        #          参数下编号跨 target 一致，docs/cli_design.md §1）
        numbered, only_sources, only_missed = filter_numbered(
            task, number_leaves(leaves), ONLY_MISS_HINT_DRIVE
        )

        # 3) resolve drive root（空/相对 → 默认会话目录下创建；绝对 → 直接创建）；
        #    末段动作（created/reused）供 merge-into 落点已存在判断
        root_file_id, root_path, root_last_action = self._resolve_root(
            task.parent_path, session_str
        )

        # 4) 构造 plan rows + 预览文案：targetPath = root + 叶子路径段；
        #    预览行用冻结编号（聚类时定，过滤不重排），供用户后续 --only 引用
        rows: list[PlanRow] = []
        preview_lines: list[str] = []
        bucket_count = 0
        root_parts = split_cloud_dir_path(root_path)

        # 3.5) merge-into 落点判定：与根目录末段同名（空白折叠，同 _resolve_root
        #      归一口径）→ 去重，落点=根目录本身（不再自嵌套 /名/名）；否则落点=
        #      根目录+merge 名。同名去重 + 目录已存在时 say 提示「并入现有文件夹」
        #      （2026-09-02 收敛：plan 期不再远程探测同名项，落点事实由 renderText
        #      尾行承载，冲突由提交时服务端报错兜底）。
        merge_deduped = False
        merge_note = ''
        merge_landing = ''
        if task.merge_into:
            root_last_seg = root_parts[-1] if root_parts else ''
            if root_last_seg and root_last_seg.strip().replace(' ', '') == (
                task.merge_into.strip().replace(' ', '')
            ):
                merge_deduped = True
                merge_landing = root_path
                if root_last_action in ('reused', 'reused_compact'):
                    merge_note = f'整理结果将并入现有文件夹 {root_path}'
            else:
                merge_landing = join_cloud_dir_path(root_parts + [task.merge_into])

        for bucket_idx, segs, bucket_files in numbered:
            # 桶名：不分桶空串、cross/hierarchical 用 '/' 拼段
            bucket_name = '/'.join(segs) if segs else ''
            bucket_count += 1
            if task.merge_into:
                # 合并目标行不占编号：bucketId 恒指冻结聚类桶，重计 1 会改写编号
                # 映射（2026-09-03 用户定案）。merge+only 时列命中源桶（冻结编号/
                # 桶名/数目）+ 合并目标行，供对照 only 是否生效；无 only 维持裸合并行
                if only_sources:
                    for src_idx, src_segs, src_count in only_sources:
                        src_name = '/'.join(src_segs) if src_segs else ''
                        preview_lines.append(
                            f'<bucketId>{src_idx}</bucketId> <bucketName>{escape(src_name or "(根目录)")}</bucketName>：{src_count} 个文件'
                        )
                    preview_lines.append(
                        f'合并到「{escape(task.merge_into)}」：{len(bucket_files)} 个文件'
                    )
                else:
                    preview_lines.append(
                        f'{escape(bucket_name or "(根目录)")}：{len(bucket_files)} 个文件'
                    )
            else:
                preview_lines.append(
                    f'<bucketId>{bucket_idx}</bucketId> <bucketName>{escape(bucket_name or "(根目录)")}</bucketName>：{len(bucket_files)} 个文件'
                )
            # 去重时落点=根目录本身（merge 名不作路径段；桶名展示仍保留 merge 名）
            target_segs = [] if merge_deduped else segs
            target_path = (
                join_cloud_dir_path(root_parts + target_segs)
                if target_segs
                else root_path
            )
            # 维度占位符取值：single 取 segs[0]；hierarchical 按维度顺序 zip；
            # cross/不分桶维度值是拼名或缺失 → 只支持 {bucket}，维度渲染为空串
            dim_values: dict[str, str] = {}
            if len(segs) == 1 and task.bucket:
                dim_values = {task.bucket: segs[0]}
            elif len(segs) > 1 and task.buckets and len(task.buckets) == len(segs):
                dim_values = dict(zip(task.buckets, segs))
            for index, f in enumerate(bucket_files, start=1):
                name = str(getattr(f, 'name', '') or '')
                rows.append(PlanRow(
                    file_id=str(getattr(f, 'file_id', '') or '').strip(),
                    bucket=bucket_name,
                    name=name,
                    index=index,
                    target_path=target_path,
                    target_file_name=(
                        render_rename_template(
                            task.rename_template,
                            bucket=bucket_name,
                            index=index,
                            name=name,
                            dim_values=dim_values,
                            file=f,
                        )
                        if task.rename_template
                        else ''
                    ),
                ))

        # 5) 写 plan.jsonl（公共库原子写，返回 planHash）
        header = PlanHeader(
            root_path=root_path,
            root_file_id=root_file_id,
            rename_template=task.rename_template,
            cluster_args={
                'mode': task.mode,
                'bucket': task.bucket,
                'buckets': list(task.buckets),
                'unknown_action': task.unknown_action,
                'only': list(task.only),
                'merge_into': task.merge_into,
                'refineKind': header_in.get('refineKind') if is_subset else '',
            },
            source='subset' if is_subset else 'search',
        )
        header_dict = header.to_dict()
        plan_hash = session.write_plan(
            header_dict, [row.to_dict() for row in rows]
        )

        # 6) meta 快照
        session.merge_meta({
            'mode': task.mode,
            'bucket': task.bucket,
            'buckets': list(task.buckets),
            'rootDirPath': root_path,
            'rootFileId': root_file_id,
            'planHash': plan_hash,
        })

        # 7) 回执：plan 一条 meta（preview + plan 合一）+ handle 行
        # merge-into 场景尾行直接给最终落点完整路径（agent 无需自行拼接根目录与
        # merge 名）；其余场景维持「根目录：…」
        tail_line = (
            f'落点：{merge_landing}' if task.merge_into else f'根目录：{root_path}'
        )
        # merge+only 首行后加命中标注（源桶行紧随其后）；无未命中省略括号尾注
        only_mark = ''
        if only_sources:
            only_mark = '--only 命中编号 ' + ','.join(str(i) for i, _, _ in only_sources)
            if only_missed:
                only_mark += '（未命中 ' + ','.join(str(i) for i in only_missed) + '）'
            only_mark += '：'
        render_text = (
            f'整理方案预览（共 {len(rows)} 个文件，{bucket_count} 个桶）：\n'
            + (f'{only_mark}\n' if only_mark else '')
            + '\n'.join(preview_lines)
            + f'\n{tail_line}'
        )
        preview_message = (
            f'已生成整理方案（共 {len(rows)} 个文件，{bucket_count} 个桶），'
            '确认后我提交'
        )
        if is_subset:
            preview_message += f'；本方案基于 refine 子集（{header_in.get("refineKind")}）'
        if unknown_count > 0 and ratio_visible:
            preview_message += (
                f'；提示：未知维度桶占比 {unknown_ratio:.1%}（{unknown_count}/{total}）'
                '，可换维度，或用 --unknown drop 处理'
            )
        preview_message += multi_label_overlap_note(
            task=task, header=header_in,
            total=len(rows), distinct=len({r.file_id for r in rows}),
        )
        if task.merge_into:
            preview_message += f'；已合并到「{task.merge_into}/」（平铺，丢弃分组目录结构）'
            if merge_note:
                preview_message += f'；{merge_note}'

        plan_rel = f'{session.id}/plan.jsonl'
        # 回执瘦身（2026-09-02）：rootDirPath/name 与 renderText 尾行「根目录：…」同值、
        # handle 与 handle 行同值，均不进 data（规则 11；rootFileId 非重复项保留）
        data: dict[str, Any] = {
            'renderText': render_text,
            'rootFileId': root_file_id,
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
            say_to_user=preview_message,
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
            'mode': task.mode,
            'bucket': task.bucket,
        }))

    # ── submit：plan.jsonl → photoOrganize/task 提交 → taskId 回执 ──

    def submit(self, task: OrganizeSubmitTask) -> int:
        # 1) 打开会话读 plan
        try:
            session = OrganizeSession.open(task.plan_handle)
        except OrganizeSessionError as exc:
            raise OperationServiceError(
                f'plan handle 不存在或格式不对：{task.plan_handle}；'
                '请用 organize --step plan 返回的 handle'
            ) from exc
        try:
            header, rows = session.read_plan()
        except OrganizeSessionError as exc:
            raise OperationServiceError(str(exc)) from exc

        # 2) organizeType / target / taskType 从 plan header 读（image=相册/回忆故事；
        #    'file' 缺省兼容旧 plan → drive 固定 task_type=1 原行为）
        organize_type = str(header.get('organizeType') or 'file').strip() or 'file'
        is_image = organize_type == 'image'
        header_target = str(header.get('target') or '').strip().lower()
        task_type: int = TASK_TYPE_DRIVE
        target_label = ''
        if is_image:
            task_type = int(header.get('taskType') or 0)
            if task_type not in _IMAGE_TARGET_LABEL:
                raise OperationServiceError(
                    f'plan header 的 taskType 非法：{task_type!r}；仅支持 album=2 / memory=3。'
                    '请用 organize --step plan --target album|memory 重新生成。'
                )
            target_label = _IMAGE_TARGET_LABEL[task_type]

        # 3) --dry-run：仅校验规划，不提交（无围栏卡，仅 meta 行）
        if task.dry_run:
            if is_image:
                image_bucket_count = len(
                    {str(r.get('targetName') or r.get('bucket') or '') for r in rows}
                )
                ok_meta(
                    'organize_submit',
                    say_to_user=(
                        f'--dry-run 校验通过：plan 含 {len(rows)} 张图、'
                        f'{image_bucket_count} 个{target_label}，未提交'
                    ),
                    data={
                        'dryRun': True,
                        'target': header_target,
                        'taskType': task_type,
                        'fileCount': len(rows),
                        'bucketCount': image_bucket_count,
                    },
                )
                return EXIT_OK
            ok_meta(
                'organize_submit',
                say_to_user=f'--dry-run 校验通过：plan 含 {len(rows)} 个整理项，未提交',
                data={
                    'dryRun': True,
                    'fileCount': len(rows),
                    'bucketCount': len({r.get('bucket') for r in rows if r.get('bucket')}),
                },
            )
            return EXIT_OK

        # 4) 解析 API 用的 session id
        session_str = resolve_current_session(required=True)
        try:
            session_id_for_api = extract_session_body(session_str)
        except Exception as exc:
            raise OperationServiceError(
                f'解析会话标识失败：{exc}；请确认 MCLAW_CURRENT_SESSION 配置正确'
            ) from exc

        # 5) 提交（server jsonl 行构造 + 业务码判定在 client 内）
        client = OrganizeTaskClient()
        try:
            result = client.submit(
                rows=rows,
                task_type=task_type,
                session_id=session_id_for_api,
                processing_hint=task.processing_hint or None,
                # image 用相册 plan 文件名（服务端按文件名区分 plan 来源）
                **({'file_name': 'album_plan.jsonl'} if is_image else {}),
            )
        except OrganizeTaskError as exc:
            raise OperationServiceError(str(exc)) from exc

        # 6) meta 记 taskId（便于后续追溯）
        session.merge_meta({
            'taskId': result.task_id,
            'submittedAt': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        })

        # 7) 回执 meta 先（fire-and-forget：不主动轮询，纪律在 SKILL.md）。
        #    同步终态（响应带 taskInfo 且终态）= 结果已在手：say 直接汇报、next 不给
        #    status 查询命令；异步与非终态保持等待话术。
        task_info = result.task_info
        task_info_dict: Optional[dict[str, Any]] = (
            task_info.to_receipt_dict() if task_info is not None else None
        )
        bucket_count = (
            len({str(r.get('targetName') or r.get('bucket') or '') for r in rows})
            if is_image
            else len({r.get('bucket') for r in rows if r.get('bucket')})
        )
        status_cmd = (
            f'python3 {_MAIN_PY} organize --step status '
            f'--task-id {result.task_id}'
        )
        submit_data: dict[str, Any] = {
            'taskId': result.task_id,
            'taskInfo': task_info_dict,
            # target 恒输出（drive 也带）：retry --target 的取值来源
            'target': header_target or 'drive',
            'fileCount': len(rows),
            'bucketCount': bucket_count,
        }
        if is_image:
            submit_data['taskType'] = task_type
        if task_info is not None and task_info.is_terminal:
            say_to_user = _terminal_say(
                task_info, _task_label_prefix(task_info.task_type or task_type)
            )
            next_steps: dict[str, str] = {}
            if task_info.status == 3:
                # 结果已在手：阻断「结果已出还提供查看链接/再查 status」的误导
                print(
                    '[INFO] 任务提交回执已直接出结果，不需要向用户提供去查看的链接',
                    flush=True,
                )
        else:
            # 处理中：say 与 taskList 卡 summary 同源（3.1 三行提交文案）
            say_to_user = build_task_submitted_summary(
                organize_task_name(task_type),
                processing_hint=task.processing_hint,
            )
            next_steps = {'status': status_cmd}
            # 轮询悬挂防线：把实值 status 命令钉在决策点（长任务上下文截断后仍可见）
            print(
                f'[INFO] 收到 <System-Event> 任务完成推送时，只执行一次: {status_cmd} ；'
                '以 status 回执为准汇报，禁止不查就报结果、禁止私自轮询、禁止重复提交',
                flush=True,
            )
        ok_meta(
            'organize_submit',
            say_to_user=say_to_user,
            next_steps=next_steps,
            data=submit_data,
        )

        # 8) 卡片块（meta 之后）——决策矩阵集中在公共库（image 需显式传 task_type
        #    才能渲染对 organizeType 与终态结果卡名，不能缺省 drive）
        emit_card_for_snapshot(
            result.task_info,
            task_id=result.task_id,
            task_type=task_type,
            results=list(result.results or []),
            organize_type=organize_type,
            processing_hint=task.processing_hint,
        )

        # 9) AI 空间动态注册（taskId 句柄，规范见 docs/dynamic_log.md）：走到这里 =
        #    提交成功（client.submit 业务码非 0000 已抛错），同步/异步均写；退出时由
        #    公共库 atexit 钩子输出 <log_path> 标记。观测副作用，写失败仅 [WARN]，
        #    不影响回执与退出码
        try:
            append_ai_space_log_record(
                resolve_ai_space_log_path(operation='organize'),
                {'taskId': result.task_id, 'taskType': 'organize'},
            )
        except Exception as exc:
            print(f'[WARN] 写入AI空间动态失败: {exc}', flush=True)

        # 10) exit code：同步终态全失败/部分失败 = 任务层业务失败（区别于调用层成功）
        if task_info is not None and task_info.is_terminal and task_info.status in (4, 5):
            return EXIT_BUSINESS_ERROR
        return EXIT_OK

    # ── status：photoOrganize/task/query 单次查询（不内部轮询）──

    def status(self, task: OrganizeTaskRef) -> int:
        client = OrganizeTaskClient()
        try:
            snap = client.query(task.task_id)
        except OrganizeTaskError as exc:
            raise OperationServiceError(str(exc)) from exc

        # retry 指引命令拼 --target（retry 必填；task_type 已知时给全，未知则留给校验报错指引）
        retry_target = _TASK_TYPE_TO_TARGET.get(int(snap.task_type or 0))
        retry_cmd = (
            f'python3 {_MAIN_PY} organize --step retry '
            f'--task-id {snap.task_id}'
            + (f' --target {retry_target}' if retry_target else '')
        )

        # 文案按快照 task_type 映射目标标签（1 归档 / 2 相册 / 3 回忆故事）
        tt = _task_label_prefix(snap.task_type)
        if snap.is_terminal:
            say = _terminal_say(snap, tt)
            # 失败终态（4/5）给 retry 指引；成功终态无下一步
            next_steps: dict[str, str] = (
                {'retry': retry_cmd} if snap.status in (4, 5) else {}
            )
        else:
            # 处理中：fire-and-forget，不主动轮询（纪律在 SKILL.md）；不发卡
            # （查看入口由提交时的 taskList 卡承载），提示只进 say（3.1 三行提交文案）
            say = build_task_submitted_summary(
                organize_task_name(int(snap.task_type or 0)),
                processing_hint=snap.processing_hint,
            )
            next_steps = {}

        # 计数只经 taskInfo 透传：平铺三计数与其完全等值，不另出（2026-09-02 瘦身）
        data: dict[str, Any] = {
            'taskId': snap.task_id,
            'isTerminal': snap.is_terminal,
            'continuePoll': not snap.is_terminal,
            'taskStatus': snap.status,
            'taskInfo': snap.to_receipt_dict(),
        }
        ok_meta(
            'organize_status',
            say_to_user=say,
            next_steps=next_steps,
            data=data,
        )

        # 卡片块（meta 之后）——仅终态发（决策矩阵集中在公共库）；非终态无卡，
        # 提示走 sayToUser
        if snap.is_terminal:
            emit_card_for_snapshot(snap, processing_hint=snap.processing_hint)
        # exit code：终态 4/5 = 任务层业务失败
        return EXIT_BUSINESS_ERROR if snap.is_terminal and snap.status in (4, 5) else EXIT_OK

    # ── retry：photoOrganize/task/retry（已成功无需重试 → skipped）──

    def retry(self, task: OrganizeTaskRef) -> int:
        client = OrganizeTaskClient()
        try:
            result = client.retry(task.task_id)
        except OrganizeTaskError as exc:
            raise OperationServiceError(str(exc)) from exc

        # 渲染用 task_type 取 --target 映射（HTTP 请求仍只带 taskId）；文案标签优先
        # 服务端 taskInfo.task_type，异步（无 taskInfo）退 --target 映射
        task_type = _RETRY_TARGET_TO_TASK_TYPE.get(task.target, TASK_TYPE_DRIVE)
        task_info = result.task_info
        task_info_dict: Optional[dict[str, Any]] = (
            task_info.to_receipt_dict() if task_info is not None else None
        )
        tt = _task_label_prefix(
            task_info.task_type if task_info is not None else task_type
        )

        # skipped：任务已成功无需重试 → 仅 meta（按好消息处理），无卡
        if result.skipped:
            ok_meta(
                'organize_retry',
                say_to_user=f'{tt}已成功，无需重试（按好消息处理）',
                data={'taskInfo': task_info_dict},
            )
            return EXIT_OK

        # 同步终态 = 结果已在手：say 直接汇报、next 不给 status 查询命令；
        # 异步与非终态 = 重试已发起，fire-and-forget（纪律在 SKILL.md）；
        # 处理中 say 与 taskList 卡 summary 同源（3.1 三行提交文案）
        if task_info is not None and task_info.is_terminal:
            say_to_user = _terminal_say(task_info, tt)
            next_steps: dict[str, str] = {}
        else:
            status_cmd = (
                f'python3 {_MAIN_PY} organize --step status '
                f'--task-id {result.task_id}'
            )
            say_to_user = build_task_submitted_summary(
                organize_task_name(task_type),
                processing_hint=getattr(task_info, 'processing_hint', '') or '',
            )
            next_steps = {'status': status_cmd}
        ok_meta(
            'organize_retry',
            say_to_user=say_to_user,
            next_steps=next_steps,
            data={'taskInfo': task_info_dict},
        )

        # 卡片块（meta 之后）——决策矩阵集中在公共库；task_type/organize_type 显式传
        # （album/memory 异步 taskList 卡不能缺省 drive，公共库 organize_cards 戒律）
        emit_card_for_snapshot(
            task_info, task_id=result.task_id,
            task_type=task_type,
            organize_type=ORGANIZE_TYPE_BY_TASK.get(task_type, 'file'),
            processing_hint=getattr(task_info, 'processing_hint', '') or '',
        )
        return EXIT_OK

    # ── 整理根目录解析（测试接缝：monkeypatch OrganizeService._resolve_root）──

    @staticmethod
    def _resolve_root(parent_path: str, session_str: str) -> tuple[str, str, str]:
        """解析整理根目录 → (fileId, absPath, 末段动作)：空 → 默认会话目录（动作
        未知，空串）；绝对/相对 → 相对段拼默认会话目录后经 ``ensure_mclaw_dir_path``
        创建，末段动作 ∈ created/reused/reused_compact。"""

        def assert_under_mclaw(normalized_dir: str) -> None:
            # 空/相对分支共用：会话目录拼出的路径仍须落在 MClaw 允许空间下
            allowed = normalize_cloud_dir_path(mclaw_allowed_dir())
            if normalized_dir != allowed and not normalized_dir.startswith(allowed + '/'):
                raise OperationServiceError(
                    f'整理根目录必须在 "{mclaw_allowed_dir()}" 目录或其子目录中，'
                    f'当前为 "{normalized_dir}"；请让用户改为该空间下的目标目录。'
                )

        user_dir = str(parent_path or '').strip().replace(' ', '')

        # 绝对路径：不经会话目录，直接 ensure_mclaw_dir_path
        if user_dir.startswith('/'):
            try:
                folder = ensure_mclaw_dir_path(user_dir, error_cls=CloudPathError)
            except CloudPathError as exc:
                raise OperationServiceError(str(exc)) from exc
            except Exception as exc:
                raise OperationServiceError(
                    f'整理根目录创建失败：{exc}；请停止并交用户决策'
                ) from exc
            file_id = str(folder.get('fileId') or '').strip()
            if not file_id:
                raise OperationServiceError(
                    f'整理根目录创建失败：{user_dir} 未返回 fileId'
                )
            actions = folder.get('_segmentActions') or []
            return (
                file_id,
                normalize_cloud_dir_path(user_dir),
                actions[-1] if actions else '',
            )

        # 空 / 相对路径：都需要先解析默认会话目录
        try:
            default_file_id, default_dir = ensure_default_session_upload_parent(session_str)
        except SessionFolderError as exc:
            raise OperationServiceError(
                f'整理根目录解析失败：{exc}；请确认 MCLAW_CURRENT_SESSION 配置正确'
            ) from exc
        except Exception as exc:
            raise OperationServiceError(
                f'整理根目录解析失败：{exc}；请停止并交用户决策'
            ) from exc
        default_dir = normalize_cloud_dir_path(default_dir)

        if not user_dir:
            assert_under_mclaw(default_dir)
            return str(default_file_id or '').strip(), default_dir, ''

        # 相对路径：拼到默认会话目录后，再创建/复用
        rel_parts = split_cloud_dir_path(user_dir)
        if not rel_parts:
            return str(default_file_id or '').strip(), default_dir, ''
        base_parts = split_cloud_dir_path(default_dir)
        normalized = normalize_cloud_dir_path(join_cloud_dir_path(base_parts + rel_parts))
        assert_under_mclaw(normalized)
        try:
            folder = ensure_mclaw_dir_path(normalized, error_cls=CloudPathError)
        except CloudPathError as exc:
            raise OperationServiceError(str(exc)) from exc
        except Exception as exc:
            raise OperationServiceError(
                f'整理根目录创建失败：{exc}；请停止并交用户决策'
            ) from exc
        file_id = str(folder.get('fileId') or '').strip()
        if not file_id:
            raise OperationServiceError(
                f'整理根目录创建失败：{normalized} 未返回 fileId'
            )
        actions = folder.get('_segmentActions') or []
        return file_id, normalized, actions[-1] if actions else ''
