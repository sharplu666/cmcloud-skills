#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子集 jsonl 读写（dedup.jsonl / select.jsonl）。

子集落回整理会话目录 ``op_xxxx/``，与 search.jsonl 同族格式：
  - 首行 header：``{"record":"searchHeader", ...SearchResultsHeader 字段, "refineKind":<kind>,
    "resultRole":"refine-subset", "refineClusterArgs":{...}, "refinePick":N,
    "isFull":true, "totalCount":N}``。复用 ``searchHeader`` 门牌使 ``OrganizeSession.search_header()``
    零改动可读；``refineKind`` 存在即子集（plan 据此判定走子集读取路径）。
  - 后续每行：``{"record":"file", **File.model_dump(by_alias=True, mode='json'), "bucket":<标签或空串>}``。
    per-bucket refine 写桶 key；整集 refine 写空串（plan 侧空串 = 不分桶单叶）。

**为何不复用 ``save_search_results`` / ``read_search``**：前者不写 per-row ``bucket``、不支持
``refineKind`` 扩展键且非原子写；后者（``OrganizeSession.read_search`` / ``load_search_results``）
经 ``File.model_validate``，而 ``File`` 的 ``model_config = extra='ignore'`` 会**静默丢弃 bucket 字段**
——plan 读子集必须保留 bucket，故用本模块的 ``read_subset``。``File`` 模型字段校验仍复用
``File.model_validate``，bucket 单独取走后再 validate。

零 common/ 改动：本模块只复用公共库的 ``SearchResultsHeader``（header 字段校验）、
``_HEADER_RECORDS``（header 门牌集合）与 ``File`` 模型，不改任何公共库代码。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from mclaw.api.search_fusion import File
from mclaw.shared.organize.tools.search_results_io import (
    _HEADER_RECORDS,
    SearchResultsHeader,
)

from utils.helpers import atomic_write_text

#: refine 子集的文件名（由 kind 决定，覆盖写）
_KIND_TO_FILENAME = {'dedup': 'dedup.jsonl', 'select': 'select.jsonl'}
#: 子集 header 的 ``refineKind`` 合法值——plan 据此判定「这是子集」。
_REFINE_KINDS = ('dedup', 'select')


def read_subset_header(path: Path) -> Dict[str, Any]:
    """读子集/搜索 jsonl 首行 header；无文件或非 header 门牌返回空 dict。

    兼容 ``searchHeader``（本会话写）与 ``searchResultsArgs``（search 命令落盘）两种门牌。
    """
    if not path.is_file():
        return {}
    with path.open(encoding='utf-8') as fp:
        first = fp.readline().strip()
    if not first:
        return {}
    row = json.loads(first)
    return row if row.get('record') in _HEADER_RECORDS else {}


def is_subset_header(header: Dict[str, Any]) -> bool:
    """header 是否为 refine 子集（含 ``refineKind`` 标记）。"""
    return str(header.get('refineKind') or '').strip() in _REFINE_KINDS


def is_merged_header(header: Dict[str, Any]) -> bool:
    """header 是否为 merge 产物（``resultRole=merged`` 语料标记，非子集）。"""
    return str(header.get('resultRole') or '').strip() == 'merged'


def write_subset(
    *,
    session_dir: Path,
    kind: str,
    files_with_bucket: List[Tuple[str, File]],
    source_header: Dict[str, Any],
    refine_cluster_args: Dict[str, Any],
    pick: int,
) -> Path:
    """落 ``op_xxxx/{kind}.jsonl``：searchHeader + refine 标记 + per-row bucket，原子写。

    Args:
        session_dir: 会话目录（``op_xxxx`` 所在路径）。
        kind: ``'dedup'`` / ``'select'``，决定文件名。
        files_with_bucket: ``[(bucket_label, File), ...]``，按此顺序落盘。
        source_header: 源 search.jsonl 的 header dict（复用其 searchKind/query 等核心字段）。
        refine_cluster_args: refine 的聚类参数快照 ``{mode, bucket, buckets}``。
        pick: refine 的 pick 值（select 时 >0）。

    Returns:
        实际写入的 ``Path``（``session_dir/{kind}.jsonl``）。
    """
    # header 核心字段经公共库模型校验（保证 searchKind/fileType 非空、pageSize≥0 等），
    # 再补全缺省键（老格式无 deduplicateSimilar → False），最后展开扩展键。
    header_model = SearchResultsHeader.model_validate(source_header)
    header_row = header_model.to_row()
    header_row.pop('lastPageAfter', None)  # 子集是终态快照，无翻页游标（协议）
    header_row['record'] = 'searchHeader'  # 与 OrganizeSession.write_search 同门牌
    header_row['isFull'] = True
    header_row['totalCount'] = len(files_with_bucket)
    header_row['refineKind'] = kind
    header_row['resultRole'] = 'refine-subset'
    header_row['refineClusterArgs'] = refine_cluster_args
    header_row['refinePick'] = pick

    lines: List[str] = [json.dumps(header_row, ensure_ascii=False)]
    for bucket_label, f in files_with_bucket:
        row = f.model_dump(by_alias=True, mode='json')
        row['record'] = 'file'
        row['bucket'] = str(bucket_label or '')
        lines.append(json.dumps(row, ensure_ascii=False))

    out_path = session_dir / _KIND_TO_FILENAME[kind]
    atomic_write_text(out_path, '\n'.join(lines) + '\n')
    return out_path


def read_subset(path: Path) -> List[Tuple[str, File]]:
    """读子集 jsonl → ``[(bucket_label, File), ...]``，保留落盘顺序。

    每行取 ``bucket``（缺省 ``''``）后 pop ``record``/``bucket`` 再 ``File.model_validate``，
    故 bucket 字段不被 ``File`` 的 ``extra='ignore'`` 丢弃。非 ``record=file`` 行跳过。
    """
    out: List[Tuple[str, File]] = []
    if not path.is_file():
        return out
    with path.open(encoding='utf-8') as fp:
        for line_no, raw in enumerate(fp, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f'子集文件第 {line_no} 行不是合法 JSON: {exc}'
                ) from exc
            if row.get('record') != 'file':
                continue
            bucket = str(row.pop('bucket', '') or '')
            row.pop('record', None)
            out.append((bucket, File.model_validate(row)))
    return out


__all__ = [
    'write_subset',
    'read_subset',
    'read_subset_header',
    'is_subset_header',
    'is_merged_header',
]
