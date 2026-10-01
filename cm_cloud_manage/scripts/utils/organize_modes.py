#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""--mode / --bucket 分桶参数解析（organize 与 refine 共用的纯函数）。

仅做字符串推导与文案生成，不抛业务异常、不 import services/cli——校验失败以
``error_msg`` 返回，由 cli 调用侧转 ``CliValidationError``。
"""
from __future__ import annotations

import re
from typing import List, Tuple

#: 多维度分桶模式：cross（拼名单层）/ hierarchical（嵌套目录）
MODES = ('cross', 'hierarchical')


def resolve_mode_bucket(
    mode_raw: str,
    bucket_raw: str,
) -> Tuple[str, str, List[str], str]:
    """解析 ``--mode`` / ``--bucket`` → ``(mode, bucket, buckets, error_msg)``。

    不传 mode + 无 bucket → 不分桶（``('', '', [])``）；+1 维 → ``single``；
    ≥2 维 → 默认 ``hierarchical``。单维度 + mode 语义无歧义，宽容接受为 single
    （docs/cli_design.md §8）。校验失败时 ``error_msg`` 非空，其余返回值无意义。
    """
    mode = str(mode_raw or '').strip().lower()
    buckets = [b.strip() for b in str(bucket_raw or '').split(',') if b.strip()]

    if mode:
        if mode not in MODES:
            if mode == 'single':
                return '', '', [], (
                    '参数错误：单维度直接传 --bucket（如 --bucket fileExtension）即可，'
                    '无需 --mode single；--mode 仅用于多维度的 cross（拼名单层）'
                    '/ hierarchical（嵌套目录）。'
                )
            return '', '', [], (
                f'参数错误：--mode 仅支持 {" / ".join(MODES)}；'
                f'当前传的是 {mode_raw!r}。'
            )
        if not buckets:
            return '', '', [], (
                f'参数错误：--mode {mode} 需要搭配 --bucket'
                '（逗号分隔的 CSV，如 year,fileExtension）。'
            )
        if len(buckets) == 1:
            return 'single', buckets[0], [], ''
        return mode, '', buckets, ''
    # 不传 mode：按维度数推导
    if not buckets:
        return '', '', [], ''
    if len(buckets) == 1:
        return 'single', buckets[0], [], ''
    return 'hierarchical', '', buckets, ''



# ──────────────────────── --rename-template 校验与渲染 ────────────────────────

#: 基础占位符（渲染原生支持的 4 个）
BASE_PLACEHOLDERS = ('bucket', 'index', 'name', 'ext')

_RENAME_FORBIDDEN_CHARS = re.compile(r'[\x00-\x1f\\/:\*\?"<>\|]')


def _sanitize_filename(name: str) -> str:
    """清理文件名：去控制字符 / 路径分隔符，并折叠 ``.`` / ``..`` 段防逃逸。"""
    cleaned = _RENAME_FORBIDDEN_CHARS.sub('_', str(name or '').strip())
    parts = [p for p in cleaned.split('/') if p not in ('', '.', '..')]
    return '/'.join(parts) if parts else 'file'


def _registered_bucket_names() -> List[str]:
    from mclaw.shared.organize.bucket import cli_help  # noqa: F401 触发注册
    from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY
    return sorted(BUCKET_REGISTRY)


def _render_rename(
    template: str, *, bucket: str, index: int, name: str,
    dim_values: dict | None = None,
) -> str:
    """渲染 ``{bucket}/{index}/{name}/{ext}/{维度}`` 占位符；index 1 起补零 3 位。

    dim_values 为维度占位符取值（``{维度名: 桶段值}``，由调用方按 --bucket 与
    桶段构造）；未含的维度渲染为空串。"""
    base, _, ext = str(name).rpartition('.')
    if not base:
        base, ext = name, ''
    rendered = str(template or '')
    rendered = rendered.replace('{bucket}', str(bucket or ''))
    rendered = rendered.replace('{index}', f'{int(index):03d}')
    rendered = rendered.replace('{name}', base)
    rendered = rendered.replace('{ext}', ext)
    for dim, val in (dim_values or {}).items():
        rendered = rendered.replace('{' + str(dim) + '}', str(val or ''))
    return _sanitize_filename(rendered)


def validate_rename_template(
    template: str, *, mode: str, buckets: List[str]
) -> str:
    """校验 ``--rename-template`` 占位符，合法原样返回（大小写笔误归一成注册名
    写回），非法抛 ``ValueError``。

    白名单 = 基础 4 个（bucket/index/name/ext）∪ 全部注册桶维度。非法时报错
    列出全部非法占位符 + 完整支持清单（基础 + 全部维度）。mode/buckets 用于
    文案中的场景说明（cross/不分桶时维度占位符渲染为空串，不拦截）。
    """
    tmpl = str(template or '').strip()
    placeholders = re.findall(r'\{([^{}]+)\}', tmpl)
    legal = set(BASE_PLACEHOLDERS) | set(_registered_bucket_names())
    # 大小写宽容：{Year}/{takenyear} 归一到注册名（模型/用户易大小写笔误）
    legal_lower = {str(l).lower(): str(l) for l in legal}
    illegal: List[str] = []
    for p in placeholders:
        if p in legal:
            continue
        canon = legal_lower.get(p.lower())
        if canon:
            # 归一成注册名写回模板，渲染层 dim_values 键即注册名
            tmpl = tmpl.replace('{' + p + '}', '{' + canon + '}')
        else:
            illegal.append(p)
    if not illegal:
        return tmpl

    dims = _registered_bucket_names()
    dim_lines = ' '.join('{' + d + '}' for d in dims)
    scene = ''
    if mode == 'cross':
        scene = '；cross 模式维度值是拼名不可拆，维度占位符渲染为空串'
    elif not mode and not buckets:
        scene = '；不分桶时维度占位符渲染为空串'
    raise ValueError(
        f'参数错误：--rename-template 含不支持的占位符 '
        f'{", ".join("{" + p + "}" for p in illegal)}。'
        f'支持的占位符：基础 {" ".join("{" + b + "}" for b in BASE_PLACEHOLDERS)}；'
        f'维度 {dim_lines}（取自 --bucket 分桶值，未传入的维度渲染为空串{scene}）。'
        f"示例：--rename-template '{{month}}_{{index}}.{{ext}}'"
    )


def _bucket_key_as_str(key) -> str:
    if isinstance(key, list):
        parts = [str(x) for x in key if str(x or '').strip()]
        return '_'.join(parts) if parts else ''
    return str(key or '')


def _merge_file_dim_values(
    template: str, file, bucket_dim_values: dict | None = None
) -> dict[str, str]:
    """桶段 dim_values 优先；模板里其余注册维度占位符从单文件元数据取值。"""
    from mclaw.shared.organize.bucket import cli_help  # noqa: F401 触发注册
    from mclaw.shared.organize.bucket.registry import BUCKET_REGISTRY, build_bucket_fn

    merged = dict(bucket_dim_values or {})
    for placeholder in re.findall(r'\{([^{}]+)\}', str(template or '')):
        if placeholder in BASE_PLACEHOLDERS or placeholder in merged:
            continue
        if placeholder not in BUCKET_REGISTRY:
            continue
        merged[placeholder] = _bucket_key_as_str(
            build_bucket_fn(placeholder).bucket_key(file)
        )
    return merged


def render_rename_template(
    template: str,
    *,
    bucket: str,
    dim_values: dict,
    index: int,
    name: str,
    file=None,
) -> str:
    """渲染模板占位符：基础 4 个 + 维度占位符（``{维度名}`` → dim_values 取值）。

    dim_values 由调用方（services 层）按 ``--bucket`` 维度与桶段构造；模板中未
    由桶段提供的注册维度占位符，在传入 ``file`` 时从该文件元数据逐张取值（如
    ``--bucket takenMonth`` 时 ``{takenDay}`` 取各文件拍摄日）。仍无法解析的
    占位符整体剔除，避免残留 ``{维度}`` 字面量进文件名。index 1 起补零 3 位；
    渲染后交 ``_sanitize_filename`` 清洗。
    """
    resolved_dims = (
        _merge_file_dim_values(template, file, dim_values)
        if file is not None
        else dim_values
    )
    rendered = _render_rename(
        template,
        bucket=bucket,
        index=index,
        name=name,
        dim_values=resolved_dims,
    )
    return re.sub(r'\{[^{}]*\}', '', rendered)
