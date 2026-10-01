#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：organize —— 整理四阶段（plan / submit / status / retry）。

校验逻辑（Task dataclass / --step / --target / --from 形态 / mode+bucket 推导 /
--unknown / --only / --merge-into 等）自 cm_cloud_manage 的 cli/validators
organize 段内联迁入（本技能无 validators 模块）；「异常→回执」映射内聚在本模块
run() 内（与 cli/refine.py 同构；入口 main.py 保持纯分发）。参数全为裸字符串，
校验失败走 ``record=meta status=error`` 回执而非 argparse usage。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Union

from utils.config import EXIT_BUSINESS_ERROR, EXIT_INPUT_ERROR, EXIT_INTERNAL_ERROR, EXIT_OK
from mclaw.shared.cm_cloud.cloud_auth import mclaw_allowed_dir
from mclaw.shared.cm_cloud.session_cli_validate import MclawEnvError
from mclaw.shared.organize.organize_session import HANDLE_RE
from mclaw.shared.postprocess.paths import (
    CloudPathError,
    assert_mclaw_path_prefix,
    split_cloud_dir_path,
)
from mclaw.shared.organize.search_fetch_store import EXIT_SEARCH_YIELDED
from services.errors import CliValidationError, OperationServiceError
from services.organize.steps import OrganizeService
from services.search_fetch import FetchYield
from services.stdout_receipt import error_meta, yielded_meta
from utils.organize_modes import resolve_mode_bucket, validate_rename_template

_ORGANIZE_STEPS = ('plan', 'submit', 'status', 'retry')
_ORGANIZE_TARGETS = ('recommend', 'drive', 'album', 'memory')
#: 公共库 photo_organize_submit 的提示语上限
_PROCESSING_HINT_MAX = 250


# ──────────────────────────── 入参 Task dataclass ────────────────────────────


@dataclass(frozen=True)
class OrganizePlanTask:
    from_handle: str
    input_file: str            # 'search.jsonl' | 'select.jsonl' | 'dedup.jsonl'（--from 指向的文件）
    target: str                # 必填：'recommend'（方向推荐仅预览）| 'drive' | 'album' | 'memory'（image 流程）
    mode: str
    bucket: str
    buckets: List[str]
    parent_path: str
    rename_template: str
    unknown_action: str      # 'keep' | 'drop'
    only: List[int] = field(default_factory=list)   # 预览编号（1 起）；空=不筛
    merge_into: str = ''     # 合并成的平铺文件夹/相册名；空=不合并


@dataclass(frozen=True)
class OrganizeSubmitTask:
    plan_handle: str
    processing_hint: str
    dry_run: bool


@dataclass(frozen=True)
class OrganizeTaskRef:
    """status / retry 共用。retry 必填 target（渲染 taskList 卡与文案标签；status 恒空）。"""

    task_id: str
    target: str = ''


#: organize 各阶段校验产物的并集
OrganizeTask = Union[OrganizePlanTask, OrganizeSubmitTask, OrganizeTaskRef]


def _validate_task_id(raw: str, step: str) -> str:
    task_id = str(raw or '').strip()
    if not task_id:
        raise CliValidationError(
            f'参数错误：organize --step {step} 需要 --task-id；'
            '请传入 submit 阶段回执返回的 taskId。'
        )
    return task_id


def _validate_retry_target(ns: argparse.Namespace) -> str:
    """校验 retry 的 ``--target``：必填，仅 drive/album/memory（重试对象必是已提交
    任务，无 recommend；值取 submit 回执 ``data.target``）。仅客户端渲染用，不进
    HTTP 重试请求。"""
    target = str(getattr(ns, 'target', '') or '').strip().lower()
    if target not in ('drive', 'album', 'memory'):
        raise CliValidationError(
            f'参数错误：organize --step retry 需要 --target（drive/album/memory），'
            f'取值见 submit 回执 data.target；当前传的是 {target or "(空)"!r}。'
        )
    return target


def _validate_step(ns: argparse.Namespace) -> str:
    step = str(getattr(ns, 'step', '') or '').strip().lower()
    if not step:
        raise CliValidationError(
            '参数错误：organize 需要 --step（取值 plan/submit/status/retry）；'
            '必须显式指定阶段。'
        )
    if step not in _ORGANIZE_STEPS:
        raise CliValidationError(
            f'参数错误：organize --step 仅支持 {" / ".join(_ORGANIZE_STEPS)}；'
            f'当前传的是 {ns.step!r}。'
        )
    return step


def _validate_target(ns: argparse.Namespace) -> str:
    """校验 ``--target``（必填）：recommend 方向推荐（仅预览不落盘）/ drive 个人云目录 /
    album 相册 / memory 回忆故事。漏传报错并说明四值语义。"""
    target = str(getattr(ns, 'target', '') or '').strip().lower()
    if not target:
        raise CliValidationError(
            '参数错误：organize --step plan 需要 --target（四选一）：'
            'recommend 用户没说整理去向时先出方向推荐（仅预览不落盘）/'
            'drive 整理到个人云目录 / album 相册 / memory 回忆故事。'
        )
    if target not in _ORGANIZE_TARGETS:
        raise CliValidationError(
            f'参数错误：organize --target 仅支持 {" / ".join(_ORGANIZE_TARGETS)}'
            f'（recommend 方向推荐仅预览不落盘；'
            f'drive 整理到个人云目录 / album 相册 / memory 回忆故事）；'
            f'当前传的是 {getattr(ns, "target", "")!r}。'
        )
    return target


#: plan 阶段 --from 的文件名白名单（submit 只认 plan.jsonl，见 _parse_submit_from）
_FROM_DATA_FILES = ('search.jsonl', 'merged.jsonl', 'select.jsonl', 'dedup.jsonl')


def _parse_from_handle_file(ns: argparse.Namespace, *, cmd: str) -> Tuple[str, str]:
    """解析 ``--from`` → ``(handle, filename)``（必须显式带数据文件，无默认值）。

    接受形式（仅显式两种，文件名限白名单 ``search.jsonl / select.jsonl /
    dedup.jsonl``——plan.jsonl 等整理产物误传在此层拦截）：
      - ``op_a3f2c1/<白名单文件>.jsonl``           → ``('op_a3f2c1', '<文件>.jsonl')``
      - ``/abs/.../op_a3f2c1/<白名单文件>.jsonl``  → ``('op_a3f2c1', '<文件>.jsonl')``

    拒绝：裸 handle（``op_a3f2c1``）、指向会话目录的绝对路径（basename 即 handle）、
    非 handle 目录段、白名单外文件名。``cmd`` 仅用于报错文案（区分 refine /
    organize --step plan）。纯形态校验，不触文件系统。
    """
    from_raw = str(getattr(ns, 'from_handle', '') or '').strip()
    if not from_raw:
        raise CliValidationError(
            f'参数错误：{cmd} 需要 --from <handle>/<文件>.jsonl；'
            '请传 search 搜索回执返回的 handle 加数据文件（如 op_<6位编码>/search.jsonl）。'
        )
    handle = ''
    filename = ''
    if from_raw.startswith('/'):
        # 形态 1：绝对路径 …/<handle>/<file>.jsonl
        parts = Path(from_raw).parts
        if len(parts) >= 2 and HANDLE_RE.fullmatch(parts[-2]):
            handle, filename = parts[-2], parts[-1]
        elif HANDLE_RE.fullmatch(Path(from_raw).name):
            # 绝对路径 basename 即 handle：指向的是会话目录而非数据文件
            raise CliValidationError(
                f'参数错误：{cmd} 的 --from 指向的是会话目录而非数据文件；'
                f'当前传的是 {from_raw!r}。请补上文件名（search.jsonl / select.jsonl / dedup.jsonl）。'
            )
    elif '/' in from_raw:
        # 形态 2：相对 op_xxxx/<file>.jsonl
        head, _, tail = from_raw.partition('/')
        if HANDLE_RE.fullmatch(head):
            handle, filename = head, tail
    if handle:
        if filename in _FROM_DATA_FILES:
            return handle, filename
        raise CliValidationError(
            f'参数错误：{cmd} 的 --from 文件名只支持 {" / ".join(_FROM_DATA_FILES)}；'
            f'当前传的是 {filename!r}（plan.jsonl 是整理产物，不是 plan 阶段的输入）。'
        )
    # 裸 handle：必须显式带数据文件
    if HANDLE_RE.fullmatch(from_raw):
        if cmd == 'refine':
            raise CliValidationError(
                f'参数错误：refine 的 --from 必须显式带数据文件，不接受裸 handle；'
                f'当前传的是 {from_raw!r}。请改为 {from_raw}/search.jsonl'
                '（refine 只读原始 search.jsonl）。'
            )
        raise CliValidationError(
            f'参数错误：organize --step plan 的 --from 必须显式带数据文件，不接受裸 handle；'
            f'当前传的是 {from_raw!r}。读原始结果改为 {from_raw}/search.jsonl，'
            f'读合并语料改为 {from_raw}/merged.jsonl，'
            f'读 refine 子集改为 {from_raw}/select.jsonl 或 {from_raw}/dedup.jsonl。'
        )
    raise CliValidationError(
        f'参数错误：{cmd} 的 --from 只接受 op_<6位编码>/<文件>.jsonl '
        f'或等价的绝对路径形式；当前传的是 {from_raw!r}。'
    )


def _resolve_mode_bucket(ns: argparse.Namespace) -> Tuple[str, str, List[str]]:
    """解析 ``--mode`` / ``--bucket`` → ``(mode, bucket, buckets)``（utils 共享纯函数）；
    缺省 None（不传），显式传空/纯空白 → 参数错误。"""
    for _flag, _raw in (
        ('--mode', getattr(ns, 'mode', None)),
        ('--bucket', getattr(ns, 'bucket', None)),
    ):
        if _raw is not None and not str(_raw).strip():
            raise CliValidationError(
                f'参数错误：{_flag} 不能只传空白；不使用就不传。'
            )
    mode, bucket, buckets, error_msg = resolve_mode_bucket(
        str(getattr(ns, 'mode', '') or ''),
        str(getattr(ns, 'bucket', '') or ''),
    )
    if error_msg:
        raise CliValidationError(error_msg)
    return mode, bucket, buckets


def _validate_organize_plan(ns: argparse.Namespace) -> OrganizePlanTask:
    """plan：``--from`` 只认 ``op_xxxx/<文件>.jsonl`` 或等价绝对路径；``--target``
    必填，分流——recommend 出方向推荐（仅预览不落盘）；drive 走目录整理原规则；
    album|memory 走相册/回忆故事规则。"""
    target = _validate_target(ns)
    from_handle, input_file = _parse_from_handle_file(ns, cmd='organize --step plan')
    mode, bucket, buckets = _resolve_mode_bucket(ns)

    parent_path = str(getattr(ns, 'parent_path', '') or '').strip()
    rename_template = str(getattr(ns, 'rename_template', '') or '').strip()
    if target != 'drive' and (parent_path or rename_template):
        # recommend=方向未定仅预览；相册/回忆故事无目录概念；rename 会污染 album
        # submit 的提交内容，后端不认
        raise CliValidationError(
            '参数错误：--target recommend|album|memory 不支持 --parent-path / --rename-template'
            '（recommend=方向未定仅预览；相册/回忆故事无目录概念，重命名会污染提交内容）；'
            '需要目录整理请显式 --target drive。'
        )
    # 模板占位符校验：白名单 = 基础 4 个 ∪ 全部注册桶维度；非法报错列全量清单
    if rename_template and target == 'drive':
        try:
            rename_template = validate_rename_template(
                rename_template, mode=mode, buckets=buckets
            )
        except ValueError as exc:
            raise CliValidationError(str(exc)) from exc
    # drive 绝对路径的前缀校验前移到此；相对路径无法判，交 services 拼默认目录后再校。
    # 前缀段按「空白折叠后比较」宽容匹配（与公共库 ensure_mclaw_dir_path 同口径，
    # docs/cli_design.md §8）：「AI 空间」≡「AI空间」；用户自建段内空格保留
    if parent_path.startswith('/'):
        allowed = mclaw_allowed_dir()
        try:
            assert_mclaw_path_prefix(split_cloud_dir_path(parent_path), allowed_dir=allowed)
        except CloudPathError:
            raise CliValidationError(
                f'参数错误：--parent-path 的绝对路径须在 "{allowed}" 下，'
                f'当前为 "{parent_path}"；请改用该空间下的路径，或传相对名（拼到会话默认目录后）。'
            )

    # --unknown 两态：keep（默认保留，argparse default 提供）/ drop（排除）
    unknown_raw = str(getattr(ns, 'unknown_action', 'keep') or '').strip()
    if unknown_raw in ('keep', 'drop'):
        unknown_action = unknown_raw
    else:
        raise CliValidationError(
            '参数错误：--unknown 仅支持 keep / drop，'
            f'当前传的是 {unknown_raw!r}。'
        )

    # --only：预览编号 CSV（1 起），兼容中英文逗号 + 空白
    only_raw = str(getattr(ns, 'only', '') or '').strip()
    only: List[int] = []
    if only_raw:
        parts: List[str] = [
            p for p in only_raw.replace('，', ',').replace(' ', ',').split(',') if p
        ]
        if any(not p.isdigit() for p in parts):
            raise CliValidationError(
                f'参数错误：--only 只接受数字编号（如 1,3），当前传的是 {only_raw!r}；'
                '编号取自 plan 回执 renderText（形如「1. jpg：5 个文件」）。'
            )
        only = [int(p) for p in parts]
        # --only 须与聚类维度同用：search/merged 重聚类输入不传维度时全量为单桶 1 号，
        # --only 1 恒命中全量（丢维度沿用旧编号会把「选部分」静默变「选全部」）；
        # refine 子集按自带标签分桶，编号来自标签，不受此限（docs/cli_design.md §1）
        if only and not mode and input_file in ('search.jsonl', 'merged.jsonl'):
            raise CliValidationError(
                '参数错误：--only 的编号来自聚类预览，须与 --bucket 维度同用'
                '（不聚类时全部文件为单桶，--only 无从收窄）；'
                '请补 --bucket <维度> 后按预览编号选桶，或去掉 --only。'
            )

    # --merge-into：会成为目标目录/相册名的一段，路径安全校验
    merge_into = str(getattr(ns, 'merge_into', '') or '').strip()
    if merge_into and (
        '/' in merge_into or '\\' in merge_into
        or merge_into in ('.', '..') or any(ch < ' ' for ch in merge_into)
    ):
        raise CliValidationError(
            '参数错误：--merge-into 的名称不能为空、不能含 / 或 .. 等路径字符。'
        )

    # O17：album|memory 读 search.jsonl 不分桶（无 --mode 且无 --bucket）时必须
    # --merge-into <名>——桶名即相册/回忆故事名，空名是参数缺陷；名称是用户意图，
    # 不替用户起默认名。--bucket all 同理拦截（不分 target）：归一桶名是常量 'ALL'
    # （内部标识非册名/目录名），落盘会生成名为 "ALL" 的册子/文件夹。
    # recommend 豁免（方向推荐允许不分桶，单册命名由回执层提示，
    # album/memory 重跑命令带 --merge-into 占位）。子集输入不在此限（带 bucket
    # 标签的子集册名来自标签；flat 子集漏配由 plan 执行层空桶名兜底拦截，双保险第二层）。
    _all_only = bucket == 'all' or buckets == ['all']
    if target in ('album', 'memory') and input_file in ('search.jsonl', 'merged.jsonl'):
        if (not mode and not buckets and not merge_into) or (_all_only and not merge_into):
            raise CliValidationError(
                '不分桶整理成相册/回忆故事需要名称：请加 --merge-into <名>，'
                '或用 --bucket <维度>（如 month）分桶'
            )
    elif _all_only and not merge_into:
        raise CliValidationError(
            '--bucket all 会生成名为 "ALL" 的目录/册子：请加 --merge-into <名> 指定名称，'
            '或改用 --bucket <维度>（如 month）分桶'
        )

    return OrganizePlanTask(
        from_handle=from_handle,
        input_file=input_file,
        target=target,
        mode=mode,
        bucket=bucket,
        buckets=buckets,
        parent_path=parent_path,
        rename_template=rename_template,
        unknown_action=unknown_action,
        only=only,
        merge_into=merge_into,
    )


def _parse_submit_from(from_raw: str) -> str:
    """解析 submit 的 ``--from`` → plan handle（文件名必须是 plan.jsonl）。

    与 ``_parse_from_handle_file`` 同款两形态（相对 ``op_xxxx/plan.jsonl`` /
    等价绝对路径），仅值域不同：submit 只认 plan 快照文件。纯形态校验。
    """
    handle = ''
    filename = ''
    if from_raw.startswith('/'):
        parts = Path(from_raw).parts
        if len(parts) >= 2 and HANDLE_RE.fullmatch(parts[-2]):
            handle, filename = parts[-2], parts[-1]
    elif '/' in from_raw:
        head, _, tail = from_raw.partition('/')
        if HANDLE_RE.fullmatch(head):
            handle, filename = head, tail
    if handle and filename == 'plan.jsonl':
        return handle
    if not filename and HANDLE_RE.fullmatch(from_raw):
        raise CliValidationError(
            f'参数错误：organize --step submit 的 --from 需要 <handle>/plan.jsonl，'
            f'当前传的是裸 handle {from_raw!r}；请补 /plan.jsonl'
            '（plan 回执 next.submit 有完整命令，可直接照抄）。'
        )
    if filename:
        raise CliValidationError(
            f'参数错误：organize --step submit 的 --from 只认 <handle>/plan.jsonl'
            f'（plan 阶段产物）；当前传的是 {filename}（数据文件属于 --step plan 的输入）。'
        )
    raise CliValidationError(
        f'参数错误：organize --step submit 的 --from 只接受 <handle>/plan.jsonl'
        f'（或等价绝对路径）；当前传的是 {from_raw!r}。'
    )


def _validate_organize_submit(ns: argparse.Namespace) -> OrganizeSubmitTask:
    """submit：``--from <handle>/plan.jsonl`` 与提示语必填（超 250 字符静默截断，不报错）。"""
    from_raw = str(getattr(ns, 'from_handle', '') or '').strip()
    if not from_raw:
        raise CliValidationError(
            '参数错误：organize --step submit 需要 --from <handle>/plan.jsonl；'
            '请传 plan 阶段回执返回的快照（如 op_<6位编码>/plan.jsonl）。'
        )
    plan_handle = _parse_submit_from(from_raw)
    processing_hint = str(getattr(ns, 'processing_hint', '') or '').strip()
    if not processing_hint:
        raise CliValidationError(
            '参数错误：organize --step submit 需要 --processing-hint；'
            '请传入等待整理中的提示语（≤250 字符，由模型结合方案生成）。'
        )
    if len(processing_hint) > _PROCESSING_HINT_MAX:
        processing_hint = processing_hint[:_PROCESSING_HINT_MAX]
    return OrganizeSubmitTask(
        plan_handle=plan_handle,
        processing_hint=processing_hint,
        dry_run=bool(getattr(ns, 'dry_run', False)),
    )


def validate_organize(ns: argparse.Namespace) -> Tuple[str, OrganizeTask]:
    """organize 统一入口：校验 ``--step`` 后路由到各阶段校验，返回 ``(step, task)``。"""
    step = _validate_step(ns)
    if step == 'plan':
        return step, _validate_organize_plan(ns)
    if step == 'submit':
        return step, _validate_organize_submit(ns)
    if step in ('status', 'retry'):
        # --from 是 plan/submit 的输入参数；status/retry 只认 --task-id（不静默忽略）
        if str(getattr(ns, 'from_handle', '') or '').strip():
            raise CliValidationError(
                f'参数错误：organize --step {step} 用 --task-id 查询任务；'
                '--from 是 plan/submit 的输入参数，请去掉。'
            )
        # --target 同样按 step 分域：status 不认；retry 必填（渲染用，见 _validate_retry_target）
        if step == 'status' and str(getattr(ns, 'target', '') or '').strip():
            raise CliValidationError(
                '参数错误：organize --step status 用 --task-id 查询任务；'
                '--target 是 plan/retry 的参数，请去掉。'
            )
        task_id = _validate_task_id(str(getattr(ns, 'task_id', '') or ''), step)
        if step == 'retry':
            return step, OrganizeTaskRef(task_id=task_id, target=_validate_retry_target(ns))
        return step, OrganizeTaskRef(task_id=task_id)
    raise CliValidationError(f'参数错误：未知的 organize --step {step!r}')  # 不可达：_validate_step 已枚举


def run(args: argparse.Namespace) -> int:
    """organize 入口：校验 → OrganizeService 分发；异常梯统一转 record=meta 回执。

    ``OperationServiceError`` 是 ``RuntimeError`` 子类，必须先于 RuntimeError 捕获。
    """
    command = 'organize'
    service_exit = EXIT_OK
    try:
        step, task = validate_organize(args)
        # 透传 service 退出码：submit/status 同步终态 4/5 → EXIT_BUSINESS_ERROR（任务层）
        service_exit = OrganizeService().run(step, task)
    except CliValidationError as exc:
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except MclawEnvError as exc:
        # MCLAW 环境变量不合法归 USAGE 档（环境入参错误，修正后重跑）
        error_meta(command, exc.message, code='USAGE')
        return EXIT_INPUT_ERROR
    except OperationServiceError as exc:
        error_meta(command, exc.message)
        return EXIT_BUSINESS_ERROR
    except FetchYield as exc:
        # 让出 ≠ 失败：断点已落盘，原样重跑同一命令即从断点续拉。
        # total 为冻结展示值，恒带后缀；计数只进自然语言。
        total_part = f'/{exc.total}' if exc.total else ''
        yielded_meta(
            command,
            say_to_user=(
                f'照片较多，已读取 {exc.fetched}{total_part} 张，正在自动继续～'
                '不想等的话，直接说「就按已读取的整理」～'
            ),
            rerun_cmd='python3 main.py ' + ' '.join(sys.argv[1:]),
        )
        return EXIT_SEARCH_YIELDED
    except RuntimeError as exc:
        error_meta(command, f'服务端错误：{exc}；请停止并交用户决策，勿自动重试')
        return EXIT_BUSINESS_ERROR
    except Exception as exc:  # noqa: BLE001 兜底：任何未知异常都要给出可行动回执
        error_meta(command, f'内部错误：{type(exc).__name__}: {exc}；请停止并交用户决策')
        return EXIT_INTERNAL_ERROR
    return service_exit
