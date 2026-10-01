#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""person-search 编排：分支路由 → SearchTask → 复用 person-search full_loop（增量断点）。

分支（docs/cli_design.md §12）：
    --from + select-faces 二次：复用歧义轮 op_xxxxxx，请求 text = queryA#queryB
      （queryA 优先取 recognizeQuery JSON 的 user_query、丢弃 bindings；解析失败/
      缺键回退歧义快照 query 原话；单跳 merge/image）；
    query+file-ids 首搜：face/recognize →（歧义 → 落 ambiguity.jsonl 出 handle 终止）
      /（空壳与 10000041 = 未检出目标人脸，零命中收束）/（缺 recognizeFaceInfo 降级 fileIdList 单跳）→ text=首轮 recognize wire 原串 + skipMultimodal 二跳。
两分支共用 person-search 检索管线（full_loop：view 单页 / full 全量+增量断点），页大小恒 50；
merge/image 首页歧义由 ``on_first_response`` 守卫拦截（翻页中途出现按错误终止，不静默继续）。

断点 = op_xxxxxx/search.jsonl 增量（弃全局 search_fetch_<digest>.jsonl）；一个 op_xxxxxx
贯穿歧义态 + 最终 search.jsonl（歧义轮建、二次复用同目录）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from cli_timing import write_cli_output_line
from mclaw.shared.organize.organize_session import OrganizeSession

from services.person_search.args import PersonSearchArgs
from services.person_search.cards import emit_ambiguity
from services.person_search import full_loop
from services.person_search.recognize import (
    PersonNoTargetStop,
    call_face_recognize,
    check_person_response_success,
    is_empty_recognize_shell,
    response_requires_select_face,
    serialize_recognize_face_info,
)
from services.search.errors import SearchServiceError
from services.search.param_build import SearchTask

#: 图文搜人拉取页大小（2026-09-01 用户定案：view/full 同口径、search_fetch 续拉同值）
PERSON_PAGE_SIZE: int = 50


class PersonAmbiguityStop(Exception):
    """歧义终态信号：ambiguity.jsonl 已落盘、meta 与 selectFaceList 卡与 handle 尾行
    （params.ambiguity=true）已输出，命令按成功（exit 0）收束。

    有意不继承 RuntimeError（否则掉进 cli 异常梯的 RuntimeError 分支变 error 回执）；
    歧义是交互中间态，落 ambiguity.jsonl 供下轮 --from 承接，不产 search.jsonl。
    """


def _ambiguity_guard(resp: Any) -> None:
    """merge/image 首页响应歧义守卫（full_loop ``on_first_response`` 钩子）。

    该路径无干净的「首搜 queryA」语义（query 已是 rewriteQuery 或二次选脸），``--from``
    契约未覆盖 → 只发卡、不落 ambiguity.jsonl（待定边案）。
    """
    if response_requires_select_face(resp):
        emit_ambiguity(getattr(resp, 'ambiguity_list', None) or [], persist=False)
        raise PersonAmbiguityStop()


def _compose_query(query_a: str, query_b: str) -> str:
    """拼接 ``queryA#queryB``（后端拆段协议）。

    - queryA 非空：``f'{queryA}#{queryB}'``（后段空也保留 ``#``——后端按 ``#`` 拆段，
      后段可空；cli_design §12 协议）。
    - queryA 空（不应发生，args 已拦）：queryB 原样。

    全仓唯一知 ``#`` 协议处（原提示层职责下沉到 CLI）。
    """
    if not query_a:
        return query_b
    return f'{query_a}#{query_b}'


def _request_query_a(recognize_query: str, fallback_query: str) -> str:
    """二次请求 text 的前段 queryA：优先解析 recognizeQuery JSON 取 ``user_query``
    （丢弃 bindings）；解析失败/user_query 空 → 回退歧义快照的 query 原话
    （2026-09-14 定案：二次请求不再回传 JSON 原串）。
    """
    try:
        user_query = str(json.loads(recognize_query).get('user_query') or '').strip()
        if user_query:
            return user_query
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return fallback_query


def _first_search_param(pargs: PersonSearchArgs) -> Dict[str, Any]:
    """file-ids 首搜：face/recognize 第一跳 → 二跳 searchImagePersonParam 快照。

    第一跳 wire text 为 JSON ``{"user_query", "bindings"}``（bindings 已映射真实
    fileId）。二跳 text 原样回传该 wire 串（不拼 ``#``，供后端校验/缓存）；rewriteQuery
    等人/图信息由 ``recognizeFaceInfo`` 承载。该快照同时进请求与 header，续拉原样
    重建（recognize 第一跳不重放）。歧义时落 ambiguity.jsonl（含 recognizeQuery=
    首轮 wire 原串）出 handle 终止。
    """
    wire_text = json.dumps(
        {'user_query': pargs.query, 'bindings': pargs.bindings or []},
        ensure_ascii=False,
    )
    resp = call_face_recognize(wire_text, pargs.file_ids)
    check_person_response_success(resp)

    if response_requires_select_face(resp):
        # 歧义：落 op_xxxxxx/ambiguity.jsonl（queryA + recognizeQuery + fileIds）
        # 出 handle、发卡、终止
        emit_ambiguity(
            getattr(resp, 'ambiguity_list', None) or [],
            query=pargs.query, file_ids=list(pargs.file_ids),
            recognize_query=wire_text,
        )
        raise PersonAmbiguityStop()

    rfi = getattr(resp, 'recognize_face_info', None)
    if is_empty_recognize_shell(rfi):
        # 空壳（selectFaceList 与 rewriteQuery 均空）= 未检测到可用目标人脸；
        # 前置拦截（带空对象调 merge/image 会被判参数错误），按零命中收束
        raise PersonNoTargetStop()
    if rfi is not None:
        return {
            # text = 首轮 recognize wire 原串（不拼 #，供后端校验/缓存）
            'text': wire_text,
            'skipMultimodal': True,
            'recognizeFaceInfo': serialize_recognize_face_info(rfi),
        }
    # 后端未按预期返回 recognizeFaceInfo：降级为 fileIdList 单跳（WARN 如实告知）
    write_cli_output_line(
        '[WARN] face/recognize 无需澄清但未返回理解结果，已降级为按参考图直接搜索'
    )
    return {'text': pargs.query, 'fileIdList': list(pargs.file_ids)}


def build_person_task(
    pargs: PersonSearchArgs,
    param_payload: Dict[str, Any],
    *,
    final_query: str,
) -> SearchTask:
    """person 任务构建（searchKind=semantic-person；header/receipt query=final_query）。

    ``final_query``：进 search.jsonl header ``query`` 与回执 ``query``（首搜=queryA 原输入；
    --from=组合 queryA#queryB；直连 select-faces=query 原样）。与 ``param_payload.text``
    （发后端的 text：首搜=rewriteQuery；--from=组合；直连=query）解耦。
    """
    return SearchTask(
        search_kind='semantic-person',
        api='merge_image',
        search_type='SemanticImagePerson',
        param_key='searchImagePersonParam',
        param_payload=param_payload,
        page_size=PERSON_PAGE_SIZE,
        header_file_type='image',
        header_query=final_query,
        receipt_query=final_query,
        mode=pargs.mode,
    )


def run_person_search(pargs: PersonSearchArgs) -> None:
    """person-search 入口：构建 person 任务后交给 person-search 检索管线（view/full 增量断点）。"""
    if pargs.from_handle:
        # 选脸二次（--from）：复用歧义轮 op_xxxxxx，单跳。请求 text 与展示口径
        # 同为 queryA#queryB——queryA 优先取 recognizeQuery JSON 的 user_query
        # （丢弃 bindings），解析失败/缺键回退歧义快照 query（2026-09-14 定案，
        # 取代原「recognizeQuery 原串#queryB」口径）
        session = OrganizeSession.open(pargs.from_handle)
        param_payload = {
            'text': _compose_query(
                _request_query_a(pargs.loaded_recognize_query, pargs.loaded_query_a),
                pargs.query,
            ),
            'selectFaceList': list(pargs.select_faces or []),
        }
        final_query = _compose_query(pargs.loaded_query_a, pargs.query)
    else:
        # 首搜（file-ids 两跳）：face/recognize（歧义则落 ambiguity.jsonl 出 handle 终止）；
        # args 已保证无 --from 时必传 --file-ids（select-faces 直连形态已废）
        param_payload = _first_search_param(pargs)
        final_query = pargs.query
        session = OrganizeSession.create()  # 无歧义才建 search 用的 op_xxxxxx
    task = build_person_task(pargs, param_payload, final_query=final_query)
    full_loop.run_person_search(task, session=session, on_first_response=_ambiguity_guard)


__all__ = [
    'PERSON_PAGE_SIZE',
    'PersonAmbiguityStop',
    'build_person_task',
    'run_person_search',
]
