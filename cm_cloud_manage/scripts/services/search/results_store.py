#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索结果落盘到 handle 目录的 ``search.jsonl``。

search 直接产 handle（``OrganizeSession.create()`` → ``op_xxx/``），结果写进该 handle
的 ``search.jsonl``，回执出 ``handle``（短 id），下游 plan 凭 handle 就地读、零拷贝。
不再产生外部 flat 文件 ``search_result_for_search_reuse_<stamp>.jsonl``。

序列化复用公共库 tools 版（``save_search_results``，doorplate ``searchResultsArgs`` +
Pydantic by_alias 保留 null + ``isFull``/``totalCount``）；落盘原子写（tempfile +
``os.replace``，先写同目录临时文件再替换，避免半截文件被下游当作完整结果消费）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mclaw.api.search_fusion import File
from mclaw.shared.organize.organize_session import OrganizeSession, OrganizeSessionError
from mclaw.shared.organize.tools.search_results_io import (
    SearchResultsHeader,
    save_search_results,
)

from services.search.errors import SearchServiceError
from services.search.param_build import SearchTask


def save_results(
    task: SearchTask,
    rows: List[Dict[str, Any]],
    *,
    output_path: Path,
    is_full: bool = True,
    total_count: int = 0,
    last_page_after: Any = None,
    semantic_info: Optional[str] = None,
) -> Path:
    """把去重后的归一化行落盘到 ``output_path``（handle 的 search.jsonl），返回该路径。

    归一化 16 键行 → 公共库 ``File`` 模型（缺省字段补 None，落盘保留 null）。
    ``is_full``/``total_count``/``last_page_after`` 写入 header 完整性字段
    （公共库 ``SearchResultsHeader`` 建模，``exclude_none`` 缺省不写键）：
    正常翻完=true、view/OOM=false。下游全量保障（``ensure_full_results``）据 ``isFull``
    检测1短路（已全零网络直导）或就地续拉（部分快照补全）。
    ``semantic_info``（语义搜图首页冻结值）注入 header 的 ``searchImageParam``
    快照——卡片 = 请求 = 落盘同形态，续拉整区灌回自动携带。
    失败转 ``SearchServiceError``（内部错误文案）。
    """
    try:
        files = [File.model_validate(row) for row in rows]
        image_param: Optional[Dict[str, Any]] = None
        if task.param_key == 'searchImageParam':
            image_param = dict(task.param_payload)
            if semantic_info:
                image_param['semanticInfo'] = semantic_info
        tmp_path = output_path.with_name(f'{output_path.name}.tmp{os.getpid()}')
        if task.param_key == 'searchImagePersonParam':
            # person header 本地落盘（公共库 save_search_results 无第四参数槽；
            # 2026-09-01 定案公共库零改动——searchImagePersonParam 以扩展键写入，
            # 读侧 search_fetch runner 的扩展键回填天然容忍）
            person_param = dict(task.param_payload)
            if semantic_info:
                person_param['semanticInfo'] = semantic_info
            _write_person_results(
                task, files, person_param, tmp_path,
                is_full=is_full, total_count=total_count,
                last_page_after=last_page_after,
            )
            os.replace(tmp_path, output_path)  # 同目录临时文件 → 原子替换
            return output_path
        save_search_results(
            search_kind=task.search_kind,
            query=task.header_query,
            file_type=task.header_file_type,
            page_size=task.page_size,
            deduplicate_similar=False,  # 本技能无相似图去重阶段，恒 false
            search_image_param=image_param,
            search_file_param=task.param_payload if task.param_key == 'searchFileParam' else None,
            search_file_dynamic_param=(
                task.param_payload if task.param_key == 'searchFileDynamicParam' else None
            ),
            files=files,
            output_path=tmp_path,
            is_full=is_full,
            total_count=total_count,
            last_page_after=last_page_after,
        )
        os.replace(tmp_path, output_path)  # 同目录临时文件 → 原子替换
        return output_path
    except SearchServiceError:
        raise
    except Exception as exc:
        raise SearchServiceError(
            f'内部错误：结果落盘失败（{type(exc).__name__}: {exc}）；请停止并交用户决策'
        ) from exc


def _write_person_results(
    task: SearchTask,
    files: List[File],
    person_param: Dict[str, Any],
    output_path: Path,
    *,
    is_full: bool,
    total_count: int,
    last_page_after: Any = None,
) -> None:
    """person 版 search.jsonl 落盘（header + file 行，与公共库格式同构）。

    header 基座字段经公共库 ``SearchResultsHeader`` 校验后回填
    ``searchImagePersonParam`` 扩展键（与读侧 runner 扩展键回填对称）；行格式与
    ``save_search_results`` 一致：``{'record': 'file', **File(by_alias)}``。
    """
    base = SearchResultsHeader(
        search_kind=task.search_kind,
        query=task.header_query,
        file_type=task.header_file_type,
        page_size=task.page_size,
        deduplicate_similar=False,
        total_count=int(total_count or 0) or None,
        last_page_after=last_page_after,
        is_full=bool(is_full),
    ).to_row()
    base['searchImagePersonParam'] = person_param
    lines = [json.dumps(base, ensure_ascii=False)]
    lines.extend(
        json.dumps(
            {'record': 'file', **f.model_dump(by_alias=True, mode='json')},
            ensure_ascii=False,
        )
        for f in files
    )
    output_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


__all__ = ['save_results']
