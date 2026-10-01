#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接口搜索结果（完整 ``List[File]``）的落盘与读回。

设计动机：
    ``search_photo_and_bucket.py`` 每次搜索都翻页拉全量，文件多时很慢；而换 bucket
    维度重新分桶只是 ``cluster_*`` 在 ``List[File]`` 上的纯函数运算，本不需要重搜。
    把完整 ``List[File]`` 落盘为权威缓存；改维度/--top 由 ``plan_for_*`` 读回再聚类，
    勿再调 search。

格式（JSONL）：
    - 第 1 行 header：``{"record":"searchResultsArgs","searchKind":...,"query":...,
      "fileType":...,"pageSize":...,"deduplicateSimilar":bool,
      "searchImageParam":({...}或{}),"searchFileParam":({...}或{}),
      "searchFileDynamicParam":({...}或{})}``；plan 头可选 ``searchResultsReusePath``
      （指向对应全量 reuse 文件）；可选完整性字段 ``totalCount``（服务端命中总数）、
      ``lastPageAfter``（末页游标，仅非 None 时写入；全量=缺省）、``isFull``（bool，
      本文件是否已含全量）——由全量拉取 / 变换（去重、精选 subset）调用方显式传入；
      普通搜索落盘不写（向后兼容，消费方以其缺失走断点/启发式检测）。
    - 后续每行：``{"record":"file", **file.model_dump(by_alias=True, mode='json')}``

header 合法性：header 行非散 dict，结构由 :class:`SearchResultsHeader` 收口（Pydantic v2
校验 + ``extra='ignore'`` 容纳 resultRole / semanticInfo 等调用方扩展字段）。
``load_search_results`` 读回时先过模型校验，再把校验后的字段以 dict 返回（向后兼容
现有 ``header.get('isFull')`` 式消费），非法 header 抛 ``ValueError``。

门牌兼容：header 的 ``record`` 行标记在落盘 reuse 文件里是 ``searchResultsArgs``，
但拷进整理会话目录后 :class:`OrganizeSession` 改用 ``searchHeader`` —— 二者内容同构。
读侧（``load_search_results``）两种门牌都认，避免同源文件因 record 名不同而读不通。

用 ``record`` 而非 ``type`` 作行标记 —— ``File`` 自身有 ``type`` 字段（值为
``'file'``/``'folder'``），用 ``type`` 会被 dump 字段覆盖。``record`` 也是本技能
既有 stdout schema 的主流约定（``previewTemplate``/``cluster_profile`` 等）。

与 ``cm_cloud_organize/scripts/search_results_io.py`` 的差异：
    - ``File`` 来源：本模块用 ``mclaw.api.search_fusion.File``（Pydantic v2 BaseModel，
      snake_case 字段 + camelCase alias），原模块用本地 ``file_model.File``
      （dataclass，camelCase 字段）。
    - 落盘：原模块 ``from plan_paths import write_plan_file``（依赖
      ``manage_bootstrap.load_organize_settings().PLAN_LOG_DIR_NAME`` 与
      ``OPENCLAW_WORKSPACE`` env）；本模块**就地实现** ``write_search_results_file``，
      落盘位置完全由 ``output_path`` / ``output_dir`` 参数决定，**不读任何配置/env**。
    - 序列化：原模块用 ``dataclasses.asdict(f)``（camelCase，always full shape）；
      本模块用 ``f.model_dump(by_alias=True, mode='json')``（camelCase alias，
      保留 ``None`` 字段以对齐原 on-disk shape），读回用 ``File.model_validate(row)``。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mclaw.api.search_fusion import File


_HEADER_RECORD = 'searchResultsArgs'
#: 整理会话目录里 :class:`OrganizeSession` 用的等价门牌名（同构 header，读侧兼容）。
_SEARCH_HEADER_RECORD = 'searchHeader'
_BUCKET_ARGS_RECORD = 'BucketArgs'
_FILE_RECORD = 'file'

#: 读侧认可的 header 门牌集合。写入只产 ``searchResultsArgs``（见 :data:`_HEADER_RECORD`），
#: ``searchHeader`` 由 :class:`OrganizeSession` 写入的 search.jsonl 产生，二者同构。
_HEADER_RECORDS: FrozenSet[str] = frozenset({_HEADER_RECORD, _SEARCH_HEADER_RECORD})


class SearchResultsHeader(BaseModel):
    """搜索结果 JSONL header 行的结构契约与校验。

    落盘 / 读回时统一过此模型，使 header 不再只是「文档里描述、代码里裸 dict」——
    字段类型、必填、可选完整性字段都有显式校验，非法 header 在读回时即报错，
    而非带着坏数据流到下游断点续传 / 聚类阶段才崩。

    设计取舍：
      - ``searchKind`` 保持宽松 ``str``（非 Literal 枚举）：新场景值由各技能自行落盘，
        公共库不替技能裁决合法集，避免每加一个场景都要改公共库（searchKind 白名单
        本就在调用侧、非此模型职责）。
      - ``extra='ignore'``：容忍 resultRole / semanticInfo / hasSimilarDedup 等调用方
        扩展字段，不强制逐字段建模（它们对本模型的契约无影响）。
      - ``deduplicateSimilar`` 给缺省 ``False``：历史老文件无此键，读回时补全为
        ``False``，行为与「本技能恒 false」一致，向后兼容。
    """

    model_config = ConfigDict(extra='ignore', populate_by_name=True)

    record: str = Field(default=_HEADER_RECORD)
    search_kind: str = Field(alias='searchKind', min_length=1)
    query: str = ''
    file_type: str = Field(alias='fileType', min_length=1)
    page_size: int = Field(alias='pageSize', ge=0)
    deduplicate_similar: bool = Field(
        alias='deduplicateSimilar', default=False
    )
    search_image_param: Dict[str, Any] = Field(
        alias='searchImageParam', default_factory=dict
    )
    search_file_param: Dict[str, Any] = Field(
        alias='searchFileParam', default_factory=dict
    )
    search_file_dynamic_param: Dict[str, Any] = Field(
        alias='searchFileDynamicParam', default_factory=dict
    )
    # 完整性字段（可选，仅全量拉取 / subset 变换时显式写入）。
    total_count: int | None = Field(alias='totalCount', default=None, ge=0)
    last_page_after: Any | None = Field(alias='lastPageAfter', default=None)
    is_full: bool | None = Field(alias='isFull', default=None)

    def to_row(self) -> Dict[str, Any]:
        """以 camelCase alias 序列化回 header 行 dict（含 record 标记）。

        ``by_alias=True`` 保留磁盘 on-disk shape；``exclude_none=True`` 使可选完整性
        字段缺省时不写键——与历史落盘口径逐字节一致（无 isFull/totalCount 的文件
        仍不出现这两个键，而非写成 null）。
        """
        row = self.model_dump(by_alias=True, mode='json', exclude_none=True)
        row['record'] = self.record
        return row


def write_search_results_file(
    text: str,
    *,
    output_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    default_basename: str = 'search_results',
) -> Path:
    """落盘搜索结果 JSONL 文本，返回写入路径。

    落盘位置完全由参数决定（不读任何配置 / 环境变量）：

    - ``output_path`` 给定 → 直接落该文件（绝对路径）；
    - 否则 ``output_dir`` 给定 → ``<output_dir>/<default_basename>_<stamp>.jsonl``，
      ``stamp = datetime.now().strftime('%Y%m%d_%H%M%S')``；
    - 两者都缺 → 抛 ``ValueError``（调用方必须显式指定落盘位置）。

    Args:
        text: 要落盘的 JSONL 文本（多行，已用 ``\\n`` 连接）。
        output_path: 显式输出文件路径；给定则忽略 ``output_dir`` / ``default_basename``。
        output_dir: 输出目录；与 ``default_basename`` + 时间戳组合生成文件名。
        default_basename: ``output_dir`` 模式下的文件名前缀，默认 ``'search_results'``。

    Returns:
        实际写入的 ``Path``（已 ``resolve()``）。

    Raises:
        ValueError: ``output_path`` 与 ``output_dir`` 同时为空。
    """
    if output_path:
        p = Path(output_path).expanduser().resolve()
    elif output_dir:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        p = (
            Path(output_dir).expanduser().resolve()
            / f'{default_basename}_{stamp}.jsonl'
        )
    else:
        raise ValueError(
            '须指定 output_path 或 output_dir：落盘位置由调用方显式传入，'
            '本模块不读任何配置 / 环境变量'
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text + '\n', encoding='utf-8')
    return p


def save_search_results(
    *,
    search_kind: str,
    query: str,
    file_type: str,
    page_size: int,
    deduplicate_similar: bool,
    search_image_param: Dict[str, Any] | None,
    search_file_param: Dict[str, Any] | None,
    search_file_dynamic_param: Dict[str, Any] | None = None,
    bucket_args: Dict[str, Any] | None = None,
    files: List[File],
    output_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    default_basename: str = 'search_results',
    result_role: str = '',
    search_results_reuse_path: str = '',
    total_count: int | None = None,
    last_page_after: Any | None = None,
    is_full: bool | None = None,
) -> Path:
    """将完整 ``List[File]`` 落盘为 ``<default_basename>_<stamp>.jsonl``，返回路径。

    Args:
        search_kind: 搜索类型标识（如 ``'semantic-image'`` / ``'image-dynamic'``）。
        query: 搜索查询文本。
        file_type: 文件类型（如 ``'image'``）。
        page_size: 翻页页大小。
        deduplicate_similar: 是否对相似图片去重。
        search_image_param: ``searchImageParam`` 请求 dict（无则 ``None`` → 落盘为 ``{}``）。
        search_file_param: ``searchFileParam`` 请求 dict（无则 ``None`` → 落盘为 ``{}``）。
        search_file_dynamic_param: ``searchFileDynamicParam`` 请求 dict
            （无则 ``None`` → 落盘为 ``{}``）。
        bucket_args: 可选分桶 CLI 入参行（须含 ``record=BucketArgs``，或由本函数补全）。
        files: 完整 ``List[File]``，按行落盘。
        output_path: 显式输出文件路径；给定则忽略 ``output_dir``。
        output_dir: 输出目录（与 ``default_basename`` + 时间戳组合生成文件名）。
        default_basename: ``output_dir`` 模式下的文件名前缀。
        result_role: 可选角色标记（如 ``photo_search_reuse`` / ``photo_plan``），写入 header。
        search_results_reuse_path: 全量 reuse 落盘路径；写 plan 头时传入，便于从 plan 找回 reuse。
        total_count: 可选，服务端命中总数；写入 header ``totalCount``（完整性检测用）。
        last_page_after: 可选，末页翻页游标（全量拉取完成后为 ``None``）；写入 header
            ``lastPageAfter``。仅当 ``last_page_after`` 非 None 时写入（全量=无下一页）。
        is_full: 可选，本文件是否已含全量结果；写入 header ``isFull``（bool）。
            三个可选参数均缺省（``None``）时 header 与不扩字段前逐字节一致（向后兼容）。

    Returns:
        实际写入的 ``Path``。

    Raises:
        ValueError: ``output_path`` 与 ``output_dir`` 同时为空。
        ValidationError: header 入参违反契约（searchKind/fileType 空、pageSize 负、
            isFull/totalCount 类型错）——save 侧先校验，不把坏 header 落盘。
    """
    try:
        header_model = SearchResultsHeader(
            search_kind=search_kind,
            query=query,
            file_type=file_type,
            page_size=page_size,
            deduplicate_similar=deduplicate_similar,
            search_image_param=search_image_param or {},
            search_file_param=search_file_param or {},
            search_file_dynamic_param=search_file_dynamic_param or {},
            total_count=total_count,
            last_page_after=last_page_after,
            is_full=is_full,
        )
    except ValidationError as exc:
        raise ValueError(f'search_results header 入参不合法：{exc}') from exc

    header_row: Dict[str, Any] = header_model.to_row()
    if bool(deduplicate_similar):
        header_row['hasSimilarDedup'] = True
    role = str(result_role or '').strip()
    if role:
        header_row['resultRole'] = role
    reuse_path = str(search_results_reuse_path or '').strip()
    if reuse_path:
        header_row['searchResultsReusePath'] = reuse_path
    header = json.dumps(header_row, ensure_ascii=False)

    rows: List[str] = [header]
    if bucket_args:
        bucket_row = dict(bucket_args)
        bucket_row.setdefault('record', _BUCKET_ARGS_RECORD)
        rows.append(json.dumps(bucket_row, ensure_ascii=False))
    for f in files:
        rows.append(json.dumps(
            {'record': _FILE_RECORD, **f.model_dump(by_alias=True, mode='json')},
            ensure_ascii=False,
        ))

    text = '\n'.join(rows)
    return write_search_results_file(
        text,
        output_path=output_path,
        output_dir=output_dir,
        default_basename=default_basename,
    )


def load_search_results(path: str) -> Tuple[List[File], Dict[str, Any]]:
    """读取 ``search_results_*.jsonl``，返回 ``(files, header)``。

    header 缺失 / 文件不存在 / JSON 非法时抛 ``ValueError``，便于上层给出清晰回执。

    Args:
        path: JSONL 文件路径。

    Returns:
        ``(files, header)``：``files`` 为去重后的 ``List[File]``（按 ``fileId`` 去重，
        保留首次出现顺序）；``header`` 为 ``searchResultsArgs`` 头行 dict。

    Raises:
        ValueError: 文件不存在；未找到 header 头行；
            无有效文件记录；某行 JSON 非法；某 file 记录字段不完整（缺必填字段）；
            header 字段不合法（searchKind/fileType 空、pageSize 负、完整性字段类型错）。
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ValueError(f'search_results 文件不存在或为空: {p}')

    header: Dict[str, Any] = {}
    files: List[File] = []
    seen: set[str] = set()
    found_header = False
    found_files = False

    with p.open('r', encoding='utf-8') as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f'search_results 第 {line_number} 行不是合法 JSON: {exc}'
                ) from exc

            record = row.get('record')
            if record in _HEADER_RECORDS:
                header = row
                found_header = True
                continue
            if record == _BUCKET_ARGS_RECORD:
                continue
            if record != _FILE_RECORD:
                continue

            file_id = str(row.get('fileId') or '').strip()
            if file_id and file_id in seen:
                continue
            if file_id:
                seen.add(file_id)
            try:
                files.append(File.model_validate(row))
            except ValidationError as exc:
                raise ValueError(
                    f'search_results 第 {line_number} 行 file 记录字段不完整: {exc}'
                ) from exc
            found_files = True

    if not found_header:
        raise ValueError(
            f'未找到 searchResultsArgs/searchHeader 头行，请确认传入的是 '
            f'search_results_*.jsonl 而非其他文件: {p}'
        )
    if not found_files:
        raise ValueError(f'search_results 无有效文件记录: {p}')

    # header 结构校验（searchKind/fileType 非空、pageSize≥0、完整性字段类型正确）。
    # 非法 header（如老格式缺 deduplicateSimilar 仍放过，但 searchKind 空字符串
    # 或 isFull="maybe" 这类坏值）在此拦截，坏文件不流到下游断点续传 / 聚类阶段。
    try:
        validated = SearchResultsHeader.model_validate(header)
    except ValidationError as exc:
        raise ValueError(f'search_results header 字段不合法: {exc}') from exc
    # 返回校验后的 header：模型字段经 to_row() 补全缺省键（如老格式无
    # deduplicateSimilar → False）并按 alias 还原 camelCase，保持
    # ``header.get('isFull')`` 式消费兼容；resultRole / semanticInfo 等
    # extra='ignore' 字段不在模型内，从原始行原样回填，不丢失（下游会读回写）。
    canonical = validated.to_row()
    for k, v in header.items():
        if k not in canonical:
            canonical[k] = v
    header = canonical

    return files, header
