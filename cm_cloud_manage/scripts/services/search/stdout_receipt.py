#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索专属 stdout 回执：``searchResults`` 交接行 + 卡片块 + agent_note。

    - ``searchResults``：成功终态交接回执（view/full 同形，带 ``query`` /
      ``fileCount`` / ``dedupCount``；语义模式纯名词形态另附 ``message`` 一行
      非阻断提示；命中数两态附回执指引——命中 0 附 ``sayToUser`` 用户向无结果
      建议、0<命中数≤阈值附 ``tips`` 模型向如实汇报约束，文案与阈值见
      ``config``）；handle 不在本行——由调用方在 stdout 尾部发独立
      ``record:"handle"`` 行（cli_design.md §2 行序定案：协议行尾置防头部截断）；
    - 卡片块与 ``<agent_note>`` 为非 record 行。无 preview 摘要行（toolresult
      去重：卡片数据行已承载前 10 条展示，摘要 record 属同批数据重复进上下文）。

进度行（progress_*）与错误 / 让出回执不在本模块：前者走 manage
``services.stdout_receipt`` 公共层（同名同签名），后者由 cli 命令模块的异常梯
输出（error_meta / yielded_meta）。所有输出 ``flush=True``、``ensure_ascii=False``。
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Dict, Final, List, Optional

from utils.config import (
    SEARCH_LOW_RESULTS_TIPS_MESSAGE,
    SEARCH_LOW_RESULTS_TIPS_THRESHOLD,
    SEARCH_ZERO_RESULTS_SAY_TO_USER,
)
from services.search.args import format_datetime19
from mclaw.shared.cm_cloud.card import Card
from mclaw.shared.cm_cloud.card_meta import card_end_note
from mclaw.shared.cm_cloud.card_output import attach_semantic_info_to_search_param
from mclaw.shared.postprocess.cli_rows import format_bytes
from cli_timing import write_cli_output_line

#: 卡片展示前 N 条（工程常量；卡片数据行是唯一的展示载体，不再另发摘要 record）
CARD_DISPLAY_LIMIT: int = 10
#: loadMore 阈值：total > 此值时前端展示「查看更多」入口
LOAD_MORE_THRESHOLD: int = 10
#: 卡片 searchParam.pageInfo.pageSize 恒设值（前端翻页常量，与搜索拉取页大小解耦）
CARD_PAGE_SIZE: int = 50
#: 纯名词形态误路由提示（回执层固定文案，仅语义模式且 Task 带 keyword_hint 时附）
KEYWORD_HINT_MESSAGE: Final[str] = '提示：按文件名搜索请改用 search --keyword'

#: searchKind → 卡片名（card_toolresult_design.md §4.2）
_CARD_NAME: Final[Dict[str, str]] = {
    'semantic-image': 'imageList',
    'image-file': 'imageList',
    'image-dynamic': 'imageList',
    'file-search': 'fileList',
    'file-dynamic': 'fileList',
    'audio-dynamic': 'audioList',
    'video-dynamic': 'videoList',
    'semantic-person': 'imageList',
}
#: searchKind → 末行 summary 模板（{n}=total，接口值）
_SUMMARY_TMPL: Final[Dict[str, str]] = {
    'semantic-image': '为您找到{n}张图片',
    'image-file': '为您找到{n}张图片',
    'image-dynamic': '为您找到{n}张图片',
    'file-search': '为您找到{n}个内容',
    'file-dynamic': '为您找到{n}条动态',
    'audio-dynamic': '为您找到{n}个音频',
    'video-dynamic': '为您找到{n}个视频',
    'semantic-person': '为您找到{n}张图片',
}
#: media 卡片（audioList/videoList）——需 media_enrich 富化 duration/contentSchedule，单条加 autoRun
_MEDIA_SEARCH_KINDS: Final[frozenset] = frozenset({'audio-dynamic', 'video-dynamic'})


def _emit(payload: Dict[str, Any]) -> None:
    """输出一条 JSONL record（唯一出口，保证编码/flush 一致）。"""
    write_cli_output_line(json.dumps(payload, ensure_ascii=False))


def _emit_line(line: str) -> None:
    """卡片块逐行出口：与 record 行共用统一出口。"""
    write_cli_output_line(line)


def emit_search_results(
    *,
    search_kind: str,
    query: str = '',
    keyword: str = '',
    file_count: int = 0,
    dedup_count: Optional[int] = None,
    keyword_hint: bool = False,
    tips_prefix: str = '',
) -> None:
    """完成交接行 record=searchResults / status=ok（成功终态恰好一条）。

    本行只装计数 / 提示（``query``/``fileCount``/``dedupCount``）；handle 不在本行——
    由调用方在 stdout 尾部发独立 ``record:"handle"`` 行（``op_xxx/search.jsonl``，
    供下游 plan --from 直接引用；cli_design.md §2 行序定案：协议行尾置防头部截断）。
    view 落部分快照（isFull=false，下游 fetch_full 续拉补全）；full 已完成（isFull=true）。
    命中 0 不产 handle（不建会话目录、不落盘空文件），无 handle 尾行（fileCount=0）。

    计数口径（D26）：``fileCount``=接口 totalCount 原样透传（view/full 同口径）；
    ``dedup_count``=翻页去重后实际行数，仅落盘 isFull=true 时输出（None 省略该键）。

    ``query`` / ``keyword``：检索词原样透传，**互斥出键**（语义/person 出 ``query``，
    关键字检索/动态出 ``keyword``）；由调用方按自身场景选字段，本函数不映射 searchKind
    ——非空才输出该键，两键至多出现一个。

    ``keyword_hint``（D22）：语义模式 --query 纯名词形态时附 ``message`` 一行非阻断
    提示（固定文案），不影响 counts 等既有字段。

    回执指引（防结果过少时自动重复搜索，文案与阈值统一在 ``config``）：
    命中数 ≤ 阈值 → 附 ``tips``（模型向：如实汇报搜索条件与命中数、勿自动改条件
    重搜）；命中 0 在此之上再附 ``sayToUser``（按 searchKind 的用户向无结果建议，
    模型原样转述，searchKind 未登记则省略该键）。``tips_prefix`` 非空时前置到
    tips（仅 person-search 未检出目标人脸零命中用，文案见 ``config``）。

    注：fileCount 与卡片 loadmore.total 同值是口径巧合，非对齐约束——卡片 total
    冻结于首次非零 totalCount，且受 D14 禁改约束，不向 fileCount 对齐。
    """
    payload: Dict[str, Any] = {
        'record': 'searchResults',
        'status': 'ok',
        'searchKind': search_kind,
    }
    if query:
        payload['query'] = query
    if keyword:
        payload['keyword'] = keyword
    payload['fileCount'] = int(file_count)
    if dedup_count is not None:
        payload['dedupCount'] = int(dedup_count)
    if keyword_hint:
        payload['message'] = KEYWORD_HINT_MESSAGE
    # 回执指引（防结果过少自动重搜）：≤阈值 → tips 模型向约束；0 再叠加 sayToUser 用户向建议
    if int(file_count) <= SEARCH_LOW_RESULTS_TIPS_THRESHOLD:
        payload['tips'] = f'{tips_prefix}{SEARCH_LOW_RESULTS_TIPS_MESSAGE}'
    if int(file_count) <= 0:
        say = SEARCH_ZERO_RESULTS_SAY_TO_USER.get(search_kind)
        if say:
            payload['sayToUser'] = say
    _emit(payload)


def emit_card(
    *,
    search_kind: str,
    rows: List[Dict[str, Any]],
    total: int,
    search_param: Dict[str, Any],
    media_meta: Optional[Dict[str, Dict[str, int]]] = None,
    semantic_info: Optional[str] = None,
) -> None:
    """输出前端渲染卡片（card_toolresult_design.md §2 第 2 部分）。

    复用公共库 ``Card`` 组装（自带 ``<frontend_card>`` 包裹 + 末行 meta +
    围栏闭合）。卡片名与 summary 按 searchKind 映射。

    约束（最高优先）：
    - ``total`` 必须取自接口响应 totalCount，**原样透传，禁止改写**——前端会拿
      同一份 searchParam 再请求接口取总数展示，改写会导致展示与模型输出不一致。
    - searchParam.pageInfo.pageAfter 剔除（前端翻页自带）；pageSize 恒设
      CARD_PAGE_SIZE（前端翻页常量，与搜索拉取页大小解耦，不从 fetch pageSize 继承）。
    - ``media_meta``（仅 audio-dynamic/video-dynamic）：``{fileId: {duration, contentSchedule}}``
      富化映射，由 fetch_loop 经 media_enrich 对前 10 条预取（见 audio_video_dynamic_design.md）；
      其余 searchKind 传 None 零开销。
    - ``semantic_info``（仅语义搜图 SemanticImage 首页）：语义理解串，注入卡片首行
      ``searchImageParam.semanticInfo``，供前端「加载更多」翻页原样回传后端首页语义理解结果；
      由 fetch_loop 取首页响应透传，续传/翻页页与文件检索为 None（attach 原样不注入）。
    - 无数据行即不发卡片（不论 total：空页+非空游标+total>0 的翻页奇态下，零行卡片
      只剩 loadMore=true 与「为您找到N张」的误导 summary；命中计数仍由 searchResults
      回执承载）。命中 0 同理：空卡片零信息且白占 toolresult 上下文；
      无卡片登记时 agent_note 由公共库自动省略，searchResults 回执照常承载 fileCount。
    """
    if not rows:
        return
    card_name = _CARD_NAME[search_kind]
    # searchParam 展示规范化：剔除 pageAfter（前端翻页自带），pageSize 恒设前端翻页常量
    param = dict(search_param or {})
    page_info = dict(param.get('pageInfo') or {})
    page_info.pop('pageAfter', None)
    page_info['pageSize'] = CARD_PAGE_SIZE
    param['pageInfo'] = page_info
    # 首页 semanticInfo 注入目标随 searchKind（semantic-person → searchImagePersonParam）
    param = attach_semantic_info_to_search_param(
        param,
        semantic_info,
        param_key='searchImagePersonParam' if search_kind == 'semantic-person' else 'searchImageParam',
    )
    if search_kind == 'semantic-person' and 'searchImagePersonParam' in param:
        # semanticInfo（数千字符 base64）所在子参数置于首行末位（超长字段最后，前端契约）
        param['searchImagePersonParam'] = param.pop('searchImagePersonParam')
    header: Dict[str, Any] = {
        # loadMore 是 total 的派生布尔：跨技能前端卡片首行契约（total>10 出「查看更多」），不可省
        'loadMore': 'true' if int(total) > LOAD_MORE_THRESHOLD else 'false',
        'total': int(total),
        'searchParam': param,
    }
    display_rows = rows[:CARD_DISPLAY_LIMIT]
    is_media = search_kind in _MEDIA_SEARCH_KINDS
    # media 卡片单条时该行加 autoRun（前端自动播放，对齐旧技能 audioList/videoList）
    auto_run = is_media and len(display_rows) == 1
    card_rows = [
        _card_row(idx, row, media_meta=media_meta, auto_run=auto_run if idx == 1 else False)
        for idx, row in enumerate(display_rows, 1)
    ]
    summary = _SUMMARY_TMPL[search_kind].format(n=int(total))
    # cli 名未在公共库 CARD_META_BY_CLI 配置 → 用 summary 覆盖避免空 summary
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        for line in Card(
            card_name, card_rows, header=header, result_type='search',
            summary=summary, count=int(total),
        ).generate():
            _emit_line(line)


def emit_agent_note() -> None:
    """输出 toolresult 末尾 ``<agent_note>``（card_toolresult_design.md §2 第 3 部分）。

    复用公共库 ``card_end_note``（整进程只发一次；无卡片登记时返回空串）。
    """
    note = card_end_note()
    if note:
        write_cli_output_line(note)


def _card_row(
    index: int,
    row: Dict[str, Any],
    *,
    media_meta: Optional[Dict[str, Dict[str, int]]] = None,
    auto_run: bool = False,
) -> Dict[str, Any]:
    """归一化行 → 卡片展示行（index + 关键字段 + 人类可读 size/sizeByte）。

    size（人类单位字符串）+ sizeByte（字节 int）双字段维持现状：公共库 cli_rows
    的展示行契约（人类可读展示 + 前端精确判断各取所需），不裁剪。

    ``media_meta``（仅 audio-dynamic/video-dynamic）：查表追加 ``duration``(int ms)
    与 ``contentSchedule``(int ms)，查不到则该 key 省略（对齐旧技能 audioList/videoList）。
    ``auto_run``：该行加 ``autoRun: true``（仅 media 卡片单条时由 emit_card 传入）。
    """
    size_byte = int(row.get('size') or 0)
    # 展示层时间统一 yyyy-MM-dd HH:mm:ss（与报错/回执 echo 同口径）：API 原样
    # 14 位数字就地格式化，其余（异常值/已是可读格式）原样透传；盘上 jsonl
    # 保持 API 原样，展示与落盘解耦。
    created_raw = str(row.get('createdAt') or '')
    out: Dict[str, Any] = {
        'index': index,
        'fileId': str(row.get('fileId') or ''),
        'name': str(row.get('name') or ''),
        'category': str(row.get('category') or ''),
        'size': format_bytes(size_byte),
        'sizeByte': size_byte,
        'createdAt': (
            format_datetime19(created_raw)
            if len(created_raw) == 14 and created_raw.isdigit()
            else created_raw
        ),
        'fileExtension': str(row.get('fileExtension') or ''),
    }
    if media_meta is not None:
        meta = media_meta.get(str(row.get('fileId') or ''))
        if meta:
            if 'duration' in meta:
                out['duration'] = meta['duration']
            if 'contentSchedule' in meta:
                out['contentSchedule'] = meta['contentSchedule']
    if auto_run:
        out['autoRun'] = True
    return out


__all__ = [
    'emit_search_results',
    'emit_card',
    'emit_agent_note',
    'CARD_PAGE_SIZE',
    'CARD_DISPLAY_LIMIT',
    'LOAD_MORE_THRESHOLD',
    'KEYWORD_HINT_MESSAGE',
]
