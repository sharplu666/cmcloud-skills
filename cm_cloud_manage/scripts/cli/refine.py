#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：refine —— 对 search.jsonl 去重/精选，产 dedup.jsonl/select.jsonl 子集。

校验逻辑（RefineTask / --from 形态 / mode+bucket 推导）自 cm_cloud_manage 的
cli/validators 内联迁入（本技能无 validators 模块）；「异常→回执」映射也内聚在本
模块 run() 内（入口 main.py 保持纯分发）。参数全为裸字符串，校验失败走
``record=meta status=error`` 回执而非 argparse usage。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from utils.config import EXIT_BUSINESS_ERROR, EXIT_INPUT_ERROR, EXIT_INTERNAL_ERROR, EXIT_OK
from mclaw.shared.organize.organize_session import HANDLE_RE
from mclaw.shared.organize.search_fetch_store import EXIT_SEARCH_YIELDED
from services.errors import CliValidationError, OperationServiceError
from services.refine.steps import run_refine
from services.search_fetch import FetchYield
from services.stdout_receipt import error_meta, yielded_meta
from utils.organize_modes import resolve_mode_bucket

_REFINE_KINDS = ('dedup', 'select', 'merge')
#: dedup/select 的语料输入域（merged 是 merge 产的新语料，同样可 refine）
_CORPUS_FILES = ('search.jsonl', 'merged.jsonl')
#: merge 的输入域（search/dedup/select/merged 一切数据 jsonl；plan 等整理产物拒绝）
_MERGE_FILES = ('search.jsonl', 'dedup.jsonl', 'select.jsonl', 'merged.jsonl')


def _parse_one_from(from_raw: str) -> Tuple[str, str]:
    """解析单个 ``--from`` 条目 → ``(handle, filename)``（必须显式带数据文件，无默认值）。

    接受形式（仅显式两种，任意 ``.jsonl`` 文件名，不做白名单）：
      - ``op_a3f2c1/<文件>.jsonl``           → ``('op_a3f2c1', '<文件>.jsonl')``
      - ``/abs/.../op_a3f2c1/<文件>.jsonl``  → ``('op_a3f2c1', '<文件>.jsonl')``

    拒绝：裸 handle（``op_a3f2c1``）、指向会话目录的绝对路径（basename 即 handle）、
    非 handle 目录段、非 ``.jsonl`` 文件名。纯形态校验，不触文件系统。
    """
    from_raw = str(from_raw or '').strip()
    if not from_raw:
        raise CliValidationError(
            '参数错误：refine 需要 --from <handle>/<文件>.jsonl；'
            '请传 search 搜索回执返回的 handle 加数据文件（如 op_<6位编码>/search.jsonl）。'
        )
    if from_raw.startswith('/'):
        # 形态 1：绝对路径 …/<handle>/<file>.jsonl
        parts = Path(from_raw).parts
        if len(parts) >= 2 and HANDLE_RE.fullmatch(parts[-2]) and parts[-1].endswith('.jsonl'):
            return parts[-2], parts[-1]
        # 绝对路径 basename 即 handle：指向的是会话目录而非数据文件
        if HANDLE_RE.fullmatch(Path(from_raw).name):
            raise CliValidationError(
                f'参数错误：refine 的 --from 指向的是会话目录而非数据文件；'
                f'当前传的是 {from_raw!r}。请补上文件名（search.jsonl / select.jsonl / dedup.jsonl）。'
            )
    elif '/' in from_raw:
        # 形态 2：相对 op_xxxx/<file>.jsonl
        head, _, tail = from_raw.partition('/')
        if HANDLE_RE.fullmatch(head) and tail.endswith('.jsonl'):
            return head, tail
    # 裸 handle：必须显式带数据文件
    if HANDLE_RE.fullmatch(from_raw):
        raise CliValidationError(
            f'参数错误：refine 的 --from 必须显式带数据文件，不接受裸 handle；'
            f'当前传的是 {from_raw!r}。请改为 {from_raw}/search.jsonl'
            '（refine 只读原始 search.jsonl）。'
        )
    raise CliValidationError(
        f'参数错误：refine 的 --from 只接受 op_<6位编码>/<文件>.jsonl '
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


@dataclass(frozen=True)
class RefineTask:
    from_handle: str          # op_a3f2c1
    input_file: str           # 'search.jsonl' | 'merged.jsonl'（语料类，不接受子集再 refine）
    kind: str                 # 'dedup' | 'select'
    mode: str                 # '' | 'single' | 'cross' | 'hierarchical'
    bucket: str               # 单维度值；多维时 ''
    buckets: List[str]        # 多维 CSV 拆分；单维时空
    pick: int                 # select 时 >0；dedup 时 0


@dataclass(frozen=True)
class MergeTask:
    """merge 任务：≥2 个 (handle, filename) 输入（按输入序，重复条目已去重）。"""
    inputs: List[Tuple[str, str]]
    kind: str = 'merge'


def validate_refine(ns: argparse.Namespace):
    """refine：``--kind dedup|select`` 对语料去重/精选；``--kind merge`` 合并产新语料。"""
    kind = str(getattr(ns, 'kind', '') or '').strip().lower()
    if kind not in _REFINE_KINDS:
        raise CliValidationError(
            '参数错误：refine --kind 仅支持 dedup / select / merge；'
            '去重用 --kind dedup，精选用 --kind select --pick N，'
            '合并多 jsonl 用 --kind merge。'
        )
    if kind == 'merge':
        return _validate_merge(ns)
    return _validate_refine_corpus(ns, kind)


def _validate_merge(ns: argparse.Namespace) -> MergeTask:
    """merge：``--from`` CSV ≥2 项（search/dedup/select/merged）；拒 --pick/--mode/--bucket。"""
    if str(getattr(ns, 'pick', '') or '').strip():
        raise CliValidationError(
            '参数错误：refine --kind merge 不接受 --pick（合并不精选）；'
            '要精选请先 merge，再对 merge 产物 --kind select --pick N。'
        )
    if (str(getattr(ns, 'mode', '') or '').strip()
            or str(getattr(ns, 'bucket', '') or '').strip()):
        raise CliValidationError(
            '参数错误：refine --kind merge 不接受 --mode / --bucket（合并不分桶）；'
            '要分桶请对 merge 产物再 refine 或 organize plan。'
        )
    from_raw = str(getattr(ns, 'from_handle', '') or '').strip()
    if not from_raw:
        raise CliValidationError(
            '参数错误：refine --kind merge 需要 --from <h1>/<f1>.jsonl,<h2>/<f2>.jsonl'
            '（CSV 至少两项，文件限 search / dedup / select / merged）。'
        )
    inputs: List[Tuple[str, str]] = []
    for entry in from_raw.replace('，', ',').split(','):
        entry = entry.strip()
        if not entry:
            continue
        handle, filename = _parse_one_from(entry)
        if filename not in _MERGE_FILES:
            raise CliValidationError(
                f'参数错误：refine --kind merge 只合并数据文件'
                f'（{" / ".join(_MERGE_FILES)}）；'
                f'{filename} 是整理产物或未知文件，不能合并。'
            )
        if (handle, filename) not in inputs:
            inputs.append((handle, filename))
    if len(inputs) < 2:
        raise CliValidationError(
            '参数错误：refine --kind merge 的 --from 需要至少两个不同输入'
            '（CSV，如 op_<6位编码1>/search.jsonl,op_<6位编码2>/select.jsonl）。'
        )
    return MergeTask(inputs=inputs)


def _validate_refine_corpus(ns: argparse.Namespace, kind: str) -> RefineTask:
    """dedup/select：单输入，只认语料类文件（search/merged；拒子集再 refine、拒 CSV）。"""
    from_raw = str(getattr(ns, 'from_handle', '') or '').strip()
    if ',' in from_raw or '，' in from_raw:
        raise CliValidationError(
            f'参数错误：refine --kind {kind} 的 --from 只接受单输入'
            '（语料类文件）；要合并多个文件请用 --kind merge。'
        )
    from_handle, input_file = _parse_one_from(from_raw)
    if input_file not in _CORPUS_FILES:
        raise CliValidationError(
            f'参数错误：refine 只读语料类文件（search.jsonl / merged.jsonl），'
            f'不接受子集文件（{input_file}）；如需换维度重做 refine，'
            f'请用 {from_handle}/search.jsonl 或 {from_handle}/merged.jsonl 重来。'
        )

    # --pick：select 必填正整数且自动开去重；dedup 拒绝 --pick
    raw_pick = str(getattr(ns, 'pick', '') or '').strip()
    pick = 0
    if kind == 'select':
        if not raw_pick:
            raise CliValidationError(
                '参数错误：refine --kind select 需要 --pick <正整数>（每桶精选前 N 张）。'
            )
        try:
            pick = int(raw_pick)
        except ValueError:
            pick = -1
        if pick < 1:
            raise CliValidationError(
                f'参数错误：refine --pick 必须是正整数（如 --pick 5），当前传的是 {raw_pick!r}。'
            )
    else:  # dedup
        if raw_pick:
            raise CliValidationError(
                '参数错误：refine --kind dedup 不接受 --pick（去重不精选）；'
                '精选请用 --kind select --pick N。'
            )

    mode, bucket, buckets = _resolve_mode_bucket(ns)
    return RefineTask(
        from_handle=from_handle,
        input_file=input_file,
        kind=kind,
        mode=mode,
        bucket=bucket,
        buckets=buckets,
        pick=pick,
    )


def run(args: argparse.Namespace) -> int:
    """refine 入口：校验 → run_refine；异常梯统一转 record=meta 回执。

    ``OperationServiceError`` 是 ``RuntimeError`` 子类，必须先于 RuntimeError 捕获。
    """
    command = 'refine'
    try:
        task = validate_refine(args)
        run_refine(task)
    except CliValidationError as exc:
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
    return EXIT_OK
