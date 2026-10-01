#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""person-search 参数校验（对齐 ``services/search/args`` 职责定位）。

规则（docs/cli_design.md §12）：``--query`` 必填（无 ``--from`` 时）；``--file-ids`` 与
``--select-faces`` 必传其一、互斥；``--bindings`` 仅 ``--file-ids`` 首搜可用且必传，
``<imgN>指称原话</imgN>`` 标签与 ``--file-ids`` 一一对应（N=次序，映射真实 fileId）；
``--select-faces`` 为 SelectFaceItem JSON 数组（结构校验，原样保留不重排），
**必须与 ``--from`` 同传**（选脸二次专属；无 ``--from`` 直连形态已废）；
``--mode view|full`` 缺省 view；``--from op_xxxxxx/ambiguity.jsonl``
承接上一轮歧义 queryA（与 ``--select-faces`` 同传、与 ``--file-ids`` 互斥；有 ``--from``
时 ``--query`` 可空=只选脸 → ``queryA#``）。参数全裸字符串收参，校验失败抛
``CliValidationError``。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mclaw.api.search_fusion._models import SelectFaceItem
from mclaw.shared.organize.organize_session import HANDLE_RE

from services.errors import CliValidationError
from services.person_search.state import read_ambiguity_state

#: --from 的文件名白名单（歧义态承接专用，plan.jsonl 等误传在此层拦）
_FROM_DATA_FILES = ('ambiguity.jsonl',)


@dataclass(frozen=True)
class PersonSearchArgs:
    """校验后的 person-search 入参。"""

    query: str
    file_ids: Optional[List[str]] = None
    bindings: Optional[List[Dict[str, str]]] = None
    select_faces: Optional[List[Dict[str, Any]]] = None
    mode: str = 'view'
    from_handle: str = ''       # 裸 op_xxxxxx（--from 承接歧义）
    loaded_query_a: str = ''    # 从 ambiguity.jsonl 读回的 queryA（展示口径拼接用）
    loaded_recognize_query: str = ''  # 读回的首轮 recognize wire 原串（请求 text 拼接用）


def _parse_file_ids(raw: str) -> List[str]:
    """--file-ids CSV 解析（容忍中文逗号与空白；空项剔除）。"""
    normalized = (raw or '').replace('，', ',')
    return [x.strip() for x in normalized.split(',') if x.strip()]


def _parse_select_faces(raw: str) -> List[Dict[str, Any]]:
    """解析并校验 --select-faces JSON 数组，返回原样 dict 列表。

    结构校验走公共库 ``SelectFaceItem`` 模型（fileId + faceInfo[{x0,y0,x1,y1,…}]）；
    校验通过后保留用户原始 dict 进请求——faceInfo[].index 是用户点选顺序，
    原样透传禁止改写（docs/business_logic.md §2.6 戒律）。
    """
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise CliValidationError('--select-faces 必须是非空 JSON 数组（或单个对象）')
    for idx, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise CliValidationError(f'--select-faces 第 {idx} 项必须是对象')
        try:
            SelectFaceItem.model_validate(entry)
        except Exception as exc:
            raise CliValidationError(f'--select-faces 第 {idx} 项结构不合法：{exc}') from exc
    return data


def _parse_bindings(raw: str, file_ids: List[str]) -> List[Dict[str, str]]:
    """解析并校验 ``--bindings`` → ``[{fileId, msg}]``（fileId 为真实 fileId）。

    ``<imgN>指称原话</imgN>`` 标签形式，N=该图在 ``--file-ids`` 中的次序（1 起）；
    须一一对应：每个 fileId 恰好一条、不越界不重复、指称原话非空。
    """
    raw = (raw or '').strip()
    n_files = len(file_ids)
    if not raw:
        raise CliValidationError(
            f'person-search：--file-ids 首搜必须同传 --bindings'
            f'（<img1>~<img{n_files}>，每图一条指称原话）'
        )
    tag_map: Dict[int, str] = {}
    for m in re.finditer(r'<img(\d+)>(.*?)</img\d+>', raw, re.DOTALL):
        n = int(m.group(1))
        if n in tag_map:
            raise CliValidationError(f'person-search：--bindings <img{n}> 重复出现')
        tag_map[n] = m.group(2).strip()
    expected = set(range(1, n_files + 1))
    if not tag_map:
        raise CliValidationError(
            'person-search：--bindings 须为 <imgN>指称原话</imgN> 标签形式'
            '（N=该图在 --file-ids 中的次序）'
        )
    if set(tag_map) != expected:
        missing = '、'.join(f'<img{n}>' for n in sorted(expected - set(tag_map)))
        extra = '、'.join(f'<img{n}>' for n in sorted(set(tag_map) - expected))
        detail = f'缺 {missing}' if missing else f'多出 {extra}'
        raise CliValidationError(
            f'person-search：--bindings 须与 --file-ids 一一对应'
            f'（{n_files} 个 fileId ↔ <img1>~<img{n_files}>）：{detail}'
        )
    empty = [n for n in sorted(tag_map) if not tag_map[n]]
    if empty:
        raise CliValidationError(f'person-search：--bindings <img{empty[0]}> 指称原话为空')
    return [{'fileId': file_ids[n - 1], 'msg': tag_map[n]} for n in sorted(tag_map)]


def _split_handle_file(from_raw: str) -> Tuple[str, str]:
    """--from 形态拆分 → (handle, filename)；不触文件系统，纯形态校验。

    接受：``op_xxxxxx/ambiguity.jsonl`` / ``/abs/.../op_xxxxxx/ambiguity.jsonl`` /
    裸 ``op_xxxxxx``（补 ambiguity.jsonl）。handle 须匹配 ``op_[0-9a-f]{6}``。
    """
    raw = (from_raw or '').strip()
    handle, filename = '', ''
    if raw.startswith('/'):
        parts = Path(raw).parts
        if len(parts) >= 2 and HANDLE_RE.fullmatch(parts[-2]):
            handle, filename = parts[-2], parts[-1]
    elif '/' in raw:
        head, _, tail = raw.partition('/')
        if HANDLE_RE.fullmatch(head):
            handle, filename = head, tail
    elif HANDLE_RE.fullmatch(raw):
        handle = raw  # 裸 handle：缺文件名，下面补默认
    if not handle:
        raise CliValidationError(
            f'person-search：--from 格式不对：{raw!r}'
            '（应形如 op_<6位编码>/ambiguity.jsonl）'
        )
    if not filename:
        filename = 'ambiguity.jsonl'  # 裸 handle 默认承接歧义态
    return handle, filename


def _parse_from_handle(raw: str) -> Tuple[str, str, str, List[str]]:
    """解析 --from → (bare_handle, queryA, recognizeQuery, fileIds)。

    形态校验（``_split_handle_file``，文件名限 ambiguity.jsonl）+ ``read_ambiguity_state``
    读回；任一不符失败抛 ``CliValidationError``（USAGE）。
    """
    from_raw = (raw or '').strip()
    if not from_raw:
        return '', '', '', []
    handle, filename = _split_handle_file(from_raw)
    if filename not in _FROM_DATA_FILES:
        raise CliValidationError(
            f'person-search：--from 文件名只支持 {" / ".join(_FROM_DATA_FILES)}'
            f'；当前 {filename!r}'
        )
    query_a, recognize_query, file_ids = read_ambiguity_state(from_raw)
    return handle, query_a, recognize_query, file_ids


def validate_person_search(args: Any) -> PersonSearchArgs:
    """校验 person-search 入参（args 为裸字符串的 argparse Namespace）。"""
    from_handle_raw = str(getattr(args, 'from_handle', '') or '')
    from_handle, loaded_query_a, loaded_recognize_query, _ = _parse_from_handle(
        from_handle_raw
    )

    file_ids = _parse_file_ids(str(getattr(args, 'file_ids', '') or ''))
    select_faces_raw = str(getattr(args, 'select_faces', '') or '').strip()

    # --from XOR --file-ids（首搜用 file-ids，消歧用 --from）
    if from_handle and file_ids:
        raise CliValidationError(
            'person-search：--from（承接上一轮需要澄清）与 --file-ids（首次搜索）不可同传'
        )
    # --from 须配 --select-faces（承接歧义后须选脸）
    if from_handle and not select_faces_raw:
        raise CliValidationError(
            'person-search：--from 必须与 --select-faces 同传（承接需要澄清状态后须选脸）'
        )

    query = str(getattr(args, 'query', '') or '').strip()
    # --query 无 --from 时必填；有 --from 时可空（只选脸 → queryA#）
    if not from_handle and not query:
        raise CliValidationError('person-search：--query 搜索描述不能为空')

    # --file-ids XOR --select-faces（既有规则，仅在无 --from 时套用）
    if not from_handle:
        if file_ids and select_faces_raw:
            raise CliValidationError(
                'person-search：--file-ids（首次搜索）与 --select-faces（选脸二次搜索）'
                '互斥，只能传其一'
            )
        if not file_ids and not select_faces_raw:
            raise CliValidationError(
                'person-search：首次搜索请提供 --file-ids（参考图），'
                '选脸二次搜索请提供 --select-faces'
            )

    # --bindings 仅首搜（--file-ids）可用且必传：一对一映射真实 fileId
    bindings_raw = str(getattr(args, 'bindings', '') or '').strip()
    is_first_search = not from_handle and bool(file_ids)
    if not is_first_search and bindings_raw:
        raise CliValidationError(
            'person-search：--bindings 仅在 --file-ids 首搜时使用'
            '（选脸二次/承接歧义不传）'
        )
    bindings = _parse_bindings(bindings_raw, file_ids) if is_first_search else None

    select_faces: Optional[List[Dict[str, Any]]] = None
    if select_faces_raw:
        try:
            select_faces = _parse_select_faces(select_faces_raw)
        except json.JSONDecodeError as exc:
            raise CliValidationError(f'--select-faces JSON 解析失败：{exc}') from exc

    mode = str(getattr(args, 'mode', '') or '').strip() or 'view'
    if mode not in ('view', 'full'):
        raise CliValidationError('person-search：--mode 只支持 view（默认）或 full')

    # --select-faces 必须与 --from 同传（选脸二次专属；无 --from 直连形态已废）。
    # 置于互斥 / bindings 禁用 / JSON 解析之后：让既有报错文案先命中（如
    # file-ids+select-faces 同传仍报互斥、not-json 仍报解析失败）。
    if not from_handle and select_faces:
        raise CliValidationError(
            'person-search：--select-faces（选脸二次）必须与 '
            '--from op_<6位编码>/ambiguity.jsonl 同传'
        )

    return PersonSearchArgs(
        query=query,
        file_ids=file_ids or None,
        bindings=bindings,
        select_faces=select_faces,
        mode=mode,
        from_handle=from_handle,
        loaded_query_a=loaded_query_a,
        loaded_recognize_query=loaded_recognize_query,
    )


__all__ = ['PersonSearchArgs', 'validate_person_search']
