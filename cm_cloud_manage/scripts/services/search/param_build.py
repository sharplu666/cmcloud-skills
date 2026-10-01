#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五场景检索任务构建：cli 规范化入参 → 公共库入参模型 + 稳定参数快照。

场景路由（cli_design.md D16-D21）：
    - semantic-search --query → merge/image, SemanticImage（语义搜图）
    - search --keyword/--type image（纯图片）→ merge/image, ImageFile（拿富化行）
    - search 其余 → merge/file, File（文件/图片条件检索，缺省不递归，--recursive true 递归）
    - dynamic --type image → merge/image, ImageDynamic（图片动态）
    - dynamic --type doc / 不传 → merge/file, FileDynamic（文档动态 / 全部文件动态）

``--mode``（D20）决定拉取策略（页大小两者一致，均用场景常量）：
    - view：单页快速返回，落盘部分快照（isFull=false，下游可续拉）；
    - full：全量拉取 + 落盘 + 断点续传。
    场景常量：语义 2000 / 图片 1000 / 文件 1000 / 动态 500。

digest 稳定性纪律（checkpoint_resume_design.md §2，仅 full 模式）：``search_param_payload``
是入参的纯函数——同一 CLI 入参任意页重跑恒得同一 dict（时间窗用用户传入的
绝对值原样、翻页游标单列在 pageInfo、页大小为场景常量），由此断点 digest 一致。
例外（D24，2026-08-27）：``--end-at`` 省略时 cli 层实时取当前时间填充——重跑窗口
右端随之前移、digest 随之变化，属预期语义（「搜到现在」本来就随时间生长）；
超大结果集需稳定断点续传时请显式传 ``--end-at``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from mclaw.shared.organize.presearch_paging import (
    PRESEARCH_IMAGE_FILE_PAGE_SIZE,
    resolve_fetch_all_page_size,
    resolve_semantic_image_fetch_all_page_size,
)
from mclaw.shared.postprocess.search_param import build_search_file_param_v3

from services.atomic.client import api_batch_get_all
from services.search.args import DynamicArgs, SearchArgs
from services.search.backup_scope import resolve_backup_scope_include_ids
from services.search.errors import NonFolderScopeIds, SearchServiceError
from services.errors import OperationServiceError

#: 语义搜图固定排序：2=按相关度倒序（语义场景相关度优先；sortType/scene 等不暴露成 CLI 参数）
_SEMANTIC_SORT_TYPE = 2

#: 语义搜图关闭重排（useRerank=false，2026-09-06 定案）
_SEMANTIC_USE_RERANK = False

#: 动态场景页大小（2026-09-15 定案：1000 → 500）
_DYNAMIC_PAGE_SIZE: int = 500


@dataclass(frozen=True)
class SearchTask:
    """一个检索任务的完整描述（services 层内部流转对象）。"""

    search_kind: str                 # semantic-image / image-file / file-search / image-dynamic / file-dynamic / audio-dynamic / video-dynamic / semantic-person
    api: str                         # merge_image / merge_file
    search_type: str                 # SemanticImage / ImageFile / File / ImageDynamic / FileDynamic
    param_key: str                   # searchImageParam / searchFileParam / searchFileDynamicParam / searchImagePersonParam
    param_payload: Dict[str, Any]    # 子结构参数快照（结果文件 header 用，无 pageInfo）
    page_size: int                   # 拉取页大小（场景常量，view/full 一致）
    header_file_type: str            # 结果文件 header fileType：image / file
    header_query: str                # 结果文件 header query（仅语义搜图非空）
    receipt_query: str               # 回执 query（仅语义/person=查询文本；关键字检索/动态恒空）
    receipt_keyword: str = ''        # 回执 keyword（关键字检索/动态=关键词原样；语义模式空）
    mode: str = 'full'               # view=单页快速返回 / full=全量拉取+落盘+续传（D20）
    dynamic_window: Optional[Tuple[str, str]] = None  # 动态场景固化时间窗（让出提示用）
    keyword_hint: bool = False       # D22 --query 纯名词形态提示标记（仅语义模式；回执层渲染，不参与 digest）
    content_type: Optional[int] = None  # 动态 contentType（1图/2音/3视/4文/None全部）；audio/video 卡片富化用


def search_param_payload(
    task: SearchTask,
    page_after: Optional[List[Any]] = None,
    semantic_info: Optional[str] = None,
) -> Dict[str, Any]:
    """构建发往接口的 searchParam dict（含 pageInfo；pageAfter 为当前页游标）。

    纯函数：除 page_after / semantic_info 外不依赖任何外部状态，重跑同参数恒得同
    dict（pageAfter 由断点 digest 剔除；semanticInfo 仅显式传参时注入——语义搜图
    翻页回传冻结首页值用，digest 输入保持纯净）。
    """
    page_info: Dict[str, Any] = {'pageSize': task.page_size, 'needTotalCount': 1}
    if page_after:
        page_info['pageAfter'] = list(page_after)
    params = task.param_payload
    # semantic_info 注入目标随 param_key（图文搜人 SemanticImagePerson 的首页冻结值
    # 注入 searchImagePersonParam，续同一次检索计划——docs/full_fetch_resume.md §5）
    if semantic_info and task.param_key in ('searchImageParam', 'searchImagePersonParam'):
        params = {**task.param_payload, 'semanticInfo': semantic_info}
    return {
        'searchType': task.search_type,
        task.param_key: params,
        'pageInfo': page_info,
    }


def build_search_task(args: SearchArgs) -> SearchTask:
    """search 子命令构建入口：按 ``--query`` 是否传入路由（显式参数名区分，D12/D21）。

    - ``query`` 非空 → 语义搜图（merge/image, SemanticImage）
    - ``query`` 为空 → 文件/图片条件检索（--keyword 可选）：纯图片（--type image）
      走 merge/image（ImageFile，拿富化行 mediaMetaInfo/aiAnalysisInfo）；
      其余走 merge/file（File）。
    """
    if args.query is not None:
        return _build_semantic_task(args.query, args.mode, args.keyword_hint)
    return _build_file_task(args)


def _build_semantic_task(query: str, mode: str, keyword_hint: bool = False) -> SearchTask:
    """语义搜图（merge/image, SemanticImage）：仅 text，其余由代码固定。

    ``keyword_hint``：cli 层 D22 纯名词形态判定结果（非阻断提示标记，透传回执层）。
    """
    return SearchTask(
        search_kind='semantic-image',
        api='merge_image',
        search_type='SemanticImage',
        param_key='searchImageParam',
        param_payload={
            'text': query,
            'sortType': _SEMANTIC_SORT_TYPE,
            'useRerank': _SEMANTIC_USE_RERANK,
        },
        page_size=resolve_semantic_image_fetch_all_page_size(),
        header_file_type='image',
        header_query=query,
        receipt_query=query,
        mode=mode,
        keyword_hint=keyword_hint,
    )


def build_dynamic_task(args: DynamicArgs) -> SearchTask:
    """个人动态搜索任务构建：按 content_type 路由（用户用 --type 显式声明检索对象）。

    - ``content_type=1``（--type image）→ merge/image, ImageDynamic（图片动态，search_kind=image-dynamic）
    - ``content_type=2``（--type audio）→ merge/file, FileDynamic, contentType=2（音频动态，search_kind=audio-dynamic）
    - ``content_type=3``（--type video）→ merge/file, FileDynamic, contentType=3（视频动态，search_kind=video-dynamic）
    - ``content_type=4``（--type doc）→ merge/file, FileDynamic, contentType=4（文档动态，search_kind=file-dynamic）
    - ``content_type=None``（不传 --type）→ merge/file, FileDynamic, contentType 不下发（全部文件动态，search_kind=file-dynamic）

    audio/video 与 doc 同走 merge/file FileDynamic（探针证实，非 legacy 端点，见
    docs/audio_video_dynamic_design.md）；仅 searchKind 与卡片不同（audio-dynamic/video-dynamic
    → audioList/videoList 富化卡片）。

    时间窗固化绝对值（digest 稳定性）；``--mode`` 决定拉取策略（页大小同场景常量）。
    """
    if args.content_type == 1:
        # 图片动态：走 merge/image（ImageDynamic），下发 contentType=1
        param_payload = {
            'startTime': args.start_at,
            'endTime': args.end_at,
            'keyword': args.keyword,
            'dynamicType': args.dynamic_type,
            'contentType': 1,
        }
        return SearchTask(
            search_kind='image-dynamic',
            api='merge_image',
            search_type='ImageDynamic',
            param_key='searchFileDynamicParam',
            param_payload=param_payload,
            page_size=_DYNAMIC_PAGE_SIZE,
            header_file_type='image',
            header_query='',
            receipt_query='',
            receipt_keyword=args.keyword,
            mode=args.mode,
            dynamic_window=(args.start_at, args.end_at),
            content_type=args.content_type,
        )

    # audio(2)/video(3)/doc(4)/全部文件(不下发)：均走 merge/file（FileDynamic），仅 searchKind 与 contentType 区分
    param_payload: Dict[str, Any] = {
        'startTime': args.start_at,
        'endTime': args.end_at,
        'keyword': args.keyword,
        'dynamicType': args.dynamic_type,
    }
    if args.content_type is not None:
        param_payload['contentType'] = args.content_type
    search_kind = {2: 'audio-dynamic', 3: 'video-dynamic', 4: 'file-dynamic'}.get(
        args.content_type, 'file-dynamic'
    )
    return SearchTask(
        search_kind=search_kind,
        api='merge_file',
        search_type='FileDynamic',
        param_key='searchFileDynamicParam',
        param_payload=param_payload,
        page_size=_DYNAMIC_PAGE_SIZE,
        header_file_type='file',
        header_query='',
        receipt_query='',
        receipt_keyword=args.keyword,
        mode=args.mode,
        dynamic_window=(args.start_at, args.end_at),
        content_type=args.content_type,
    )


def _ensure_scope_ids_are_folders(ids: List[str], label: str) -> None:
    """``--scope-in``/``--scope-out`` 只收文件夹 fileId：batchGet 核类型。

    任一 id 类型不为 folder（含 batchGet 查不到的）→ ``NonFolderScopeIds``
    整体拒绝，由 cli 层组回执与 ``next.search-by-ids`` 指路。
    """
    if not ids:
        return
    try:
        items = api_batch_get_all(list(ids))
    except RuntimeError as exc:
        raise OperationServiceError(
            f'查询目录信息失败：{exc}；请停止并交用户决策，勿自动重试'
        ) from exc
    types = {}
    for item in items:
        src = item.get('srcFile') if isinstance(item.get('srcFile'), dict) else {}
        fid = str(src.get('fileId') or item.get('fileId') or '').strip()
        if fid:
            types[fid] = str(src.get('type') or '').strip()
    offenders = [fid for fid in ids if types.get(fid) != 'folder']
    if offenders:
        raise NonFolderScopeIds(
            f'{label} 只能输入文件夹 fileId，以下不是文件夹: {offenders}',
            offenders,
            label,
        )


def _build_file_task(args: SearchArgs) -> SearchTask:
    """文件/图片条件检索（--keyword 可选）：按 --type 显式路由（用户用 --type 声明检索对象）。

    - 纯图片（--type image，type_list==[1]）→ merge/image, ImageFile：拿富化行
      （mediaMetaInfo/aiAnalysisInfo）；接受 suffixList，返回富化行（实测确认，旧注释
      「服务端会拒 suffixList」为误判）。
    - 其余（多类型 / 无图片 / audio/video/doc/folder/other）→ merge/file, File（现状）。

    search 文件检索默认不递归子目录（recursion=None 不下发=仅一层）；
    --recursive 传 true 时递归全部子目录（recursion=True 下发 true）。

    ``backup_folder_names`` 非空（--backup-folder 传入）→ 先把口径目录名解析为
    fileId（services/search/backup_scope，batchCheckExists 端点），作为 include
    范围下发（原 search_backup 能力，2026-09-01 并入）。
    """
    include_ids: Optional[List[str]] = args.scope_in or None
    if args.backup_folder_names:
        # --backup-folder 与 --scope-in/out 互斥（cli 层前置拦截），此处 include_ids 恒为 None
        resolved, _names = resolve_backup_scope_include_ids(args.backup_folder_names)
        include_ids = resolved
    else:
        # scope 只收文件夹 fileId：非 folder（或查不到）整体拒绝（--backup-folder
        # 解析出的 include 恒为口径目录，免检）
        _ensure_scope_ids_are_folders(args.scope_in, '--scope-in')
    _ensure_scope_ids_are_folders(args.scope_out, '--scope-out')

    # 纯图片（--type image）走 merge/image, ImageFile（拿富化行）；其余走 merge/file, File
    if args.type_list == [1]:
        param = _build_file_param_from_filters(args, include_ids, recursion=args.recursive)
        return SearchTask(
            search_kind='image-file',
            api='merge_image',
            search_type='ImageFile',
            param_key='searchFileParam',
            param_payload=param,
            page_size=PRESEARCH_IMAGE_FILE_PAGE_SIZE,
            header_file_type='image',
            header_query='',
            receipt_query='',
            receipt_keyword=args.keyword,
            mode=args.mode,
        )

    param = _build_file_param_from_filters(
        args, include_ids, exclude_file_id_list=args.scope_out or None,
        recursion=args.recursive,
    )
    return SearchTask(
        search_kind='file-search',
        api='merge_file',
        search_type='File',
        param_key='searchFileParam',
        param_payload=param,
        page_size=resolve_fetch_all_page_size(file_types=args.type_list or None),
        header_file_type='file',
        header_query='',
        receipt_query='',
        receipt_keyword=args.keyword,
        mode=args.mode,
    )


def _build_file_param_from_filters(
    args,
    include_file_id_list: Optional[List[str]],
    exclude_file_id_list: Optional[List[str]] = None,
    *,
    recursion: bool = True,
) -> Dict[str, Any]:
    """search 的 SearchFileParamV3 构建（keyword + 过滤 + 目录范围）。

    提取为本函数复用于文件/纯图片两分支。``args`` 取 SearchArgs 的过滤字段
    （keyword/type_list/ext_list/start_at/end_at/time_field/size_min/size_max）；
    目录范围由调用方传入（--scope-in/--backup-folder 解析结果）。cli 层已前置校验，
    此处仅公共库兜底。
    """
    size_range = None
    if args.size_min is not None or args.size_max is not None:
        size_range = {'start': args.size_min, 'end': args.size_max}
    try:
        param = build_search_file_param_v3(
            keyword=args.keyword,
            file_types=args.type_list or None,
            start_at=args.start_at,
            end_at=args.end_at,
            time_field=args.time_field,
            include_file_id_list=include_file_id_list,
            exclude_file_id_list=exclude_file_id_list,
            recursion=recursion,
            size_range=size_range,
        )
    except ValueError as exc:
        # cli 层已前置校验，此处是公共库兜底（如服务端约束变更）
        raise SearchServiceError(f'参数错误：{exc}') from exc
    # 公共库 build 的 extension 参数只收单值；CLI --ext 是 CSV，此处薄封装补齐多值
    # （去 . 小写在 cli 层完成，序列化形态 suffixList 不变）
    if args.ext_list:
        param['suffixList'] = list(args.ext_list)
    return param


__all__ = [
    'SearchTask',
    'search_param_payload',
    'build_search_task',
    'build_dynamic_task',
]
