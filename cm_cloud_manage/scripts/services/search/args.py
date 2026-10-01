#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search / dynamic 两命令的入参校验与规范化。

两层合一（校验逻辑 / 输入规范化纯函数 / 备份口径白名单，校验规则与报错文案
与检索命令族既有口径逐字一致）：
    - 备份口径目录白名单常量（``--backup-folder`` 单点真相）；
    - 输入规范化纯函数（时间 / 大小 / CSV：字符串 → 规范值的确定性转换，同一输入
      恒得同一输出——这是断点 digest 稳定性的前提；解析失败抛 ``ValueError``）；
    - 全部入参校验（失败抛 ``CliValidationError``，自然语言中文，直接写明原因与
      修正提示，不使用数字退出码 / 错误码枚举）。

校验项（docs/cli_design.md §10）：--query/--keyword 互斥与 --query×过滤互斥（含
--backup-folder）、--mode 枚举（view/full）、--type 词形枚举（image/audio/video/
doc/folder/other，dynamic 受限 image/audio/video/doc/缺省）、takenAt 纯图片、
size×目录互斥、scope 互斥与 ≤20、--backup-folder 与 scope 系互斥、备份口径白名单、
时间对合法与时间上限（--start-at 不得晚于当前；--end-at 超前截断为当前并提示；省略=实时取当前）、
--kind 枚举。另含纯名词形态判定（--query 误路由防呆）：非校验、不 raise，只置
提示标记随 Task 流转，由回执层渲染固定文案。

``CliValidationError`` 不本地定义，用 manage ``services.errors`` 的同名类。
"""

from __future__ import annotations

import argparse
import calendar
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Tuple

from cli_timing import write_cli_output_line
from services.errors import CliValidationError

# ──────────────────────────── 备份口径目录白名单 ────────────────────────────

#: 账号根目录 ``/`` 下备份相关一级目录名称（``--backup-folder`` 口径白名单单一来源）。
#: 与 cli_design.md §10 / references/SEARCH-BACKUP.md 的口径目录清单一致。
BACKUP_SCOPE_ROOT_FOLDER_NAMES: Tuple[str, ...] = (
    '手机备份',
    '手机图片',
    '手机音乐',
    '手机视频',
    '同步盘',
    '139 邮箱',
    '来自电脑备份',
    '来自微信备份文件夹',
)

#: 口径名白名单（O(1) 校验）
_BACKUP_SCOPE_NAMES_SET = frozenset(BACKUP_SCOPE_ROOT_FOLDER_NAMES)


def is_valid_backup_folder_name(name: str) -> bool:
    """名称是否在备份口径白名单内（校验用，单点真相）。"""
    return name in _BACKUP_SCOPE_NAMES_SET


# ──────────────────────────── 输入规范化纯函数 ────────────────────────────

# 大小单位 → 字节（二进制口径，与服务端 sizeRange 一致）
_SIZE_UNITS = {
    '': 1, 'B': 1,
    'K': 1 << 10, 'KB': 1 << 10,
    'M': 1 << 20, 'MB': 1 << 20,
    'G': 1 << 30, 'GB': 1 << 30,
    'T': 1 << 40, 'TB': 1 << 40,
}

_SIZE_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$')
_DATE_ONLY_RE = re.compile(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$')
_MONTH_ONLY_RE = re.compile(r'^(\d{4})[-/](\d{1,2})$')
_DATETIME_RE = re.compile(
    r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$'
)

#: 支持的时间写法（报错文案用）
_TIME_FORMAT_HINT = '2026-08-01、2026/8/1、20260801、2026-08 或 2026-08-01 10:30:00'


def _fmt_date(y: int, mo: int, d: int, raw: str) -> str:
    """构造日期并校验合法性（月/日越界统一给出友好中文报错）。"""
    try:
        return datetime(y, mo, d).strftime('%Y%m%d')
    except ValueError as exc:
        raise ValueError(f'无法解析时间 {raw!r}（{exc}；请使用 {_TIME_FORMAT_HINT}）') from exc


def _fmt_datetime(y: int, mo: int, d: int, h: int, mi: int, sec: int, raw: str) -> str:
    """构造时刻并校验合法性。"""
    try:
        return datetime(y, mo, d, h, mi, sec).strftime('%Y%m%d%H%M%S')
    except ValueError as exc:
        raise ValueError(f'无法解析时间 {raw!r}（{exc}；请使用 {_TIME_FORMAT_HINT}）') from exc


def parse_time_14(value: str, *, end: bool = False) -> str:
    """解析时间入参为 14 位 ``yyyyMMddHHmmss``。

    - 日期简写按 ``end`` 补全：``end=False`` 补 ``000000``，``end=True`` 补
      ``235959``（月粒度 ``end`` 取该月最后一天，与公共库 parse_date_range_value 语义一致）；
    - 带 ``HH:mm[:ss]`` 的写法精确到秒，``end`` 不影响；
    - 14 位数字原样透传。
    """
    s = str(value or '').strip()
    if not s:
        raise ValueError('时间参数为空')
    if len(s) == 14 and s.isdigit():
        return s

    m = _DATETIME_RE.match(s)
    if m:
        y, mo, d, h, mi, sec = (int(x) for x in m.groups(default='0'))
        return _fmt_datetime(y, mo, d, h, mi, sec, s)

    m = _DATE_ONLY_RE.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _fmt_date(y, mo, d, s) + ('235959' if end else '000000')

    if s.isdigit() and len(s) == 8:
        return _fmt_date(int(s[:4]), int(s[4:6]), int(s[6:8]), s) + ('235959' if end else '000000')

    if s.isdigit() and len(s) == 6:
        y, mo = int(s[:4]), int(s[4:6])
        if not 1 <= mo <= 12:
            raise ValueError(f'无法解析时间 {s!r}（月份须在 1–12）')
        return f'{y:04d}{mo:02d}01' + ('235959' if end else '000000')

    # 带分隔符的月粒度（如 2026-08 / 2026/8）：end 取该月最后一天，非 end 取该月 1 日
    m = _MONTH_ONLY_RE.match(s)
    if m:
        y, mo = (int(x) for x in m.groups())
        if not 1 <= mo <= 12:
            raise ValueError(f'无法解析时间 {s!r}（月份须在 1–12）')
        if end:
            last_day = calendar.monthrange(y, mo)[1]
            return f'{y:04d}{mo:02d}{last_day:02d}235959'
        return f'{y:04d}{mo:02d}01000000'

    raise ValueError(f'无法解析时间 {s!r}（请使用 {_TIME_FORMAT_HINT}）')


def format_datetime19(value_14: str) -> str:
    """14 位 ``yyyyMMddHHmmss`` → 接口要求的 ``yyyy-MM-dd HH:mm:ss``。"""
    return (
        f'{value_14[0:4]}-{value_14[4:6]}-{value_14[6:8]} '
        f'{value_14[8:10]}:{value_14[10:12]}:{value_14[12:14]}'
    )


def parse_size_bytes(value: str) -> int:
    """解析 ``10MB`` / ``2G`` / ``512`` 等大小写法为字节数。"""
    s = str(value or '').strip()
    m = _SIZE_RE.match(s)
    if not m:
        raise ValueError(f'无法解析大小 {s!r}（请使用 10MB / 2G / 512KB 等写法，支持 B/KB/MB/GB/TB）')
    number, unit = m.group(1), m.group(2).upper()
    if unit not in _SIZE_UNITS:
        raise ValueError(f'大小单位 {m.group(2)!r} 不支持（支持 B/KB/MB/GB/TB）')
    return int(float(number) * _SIZE_UNITS[unit])


def parse_csv_tokens(value: str) -> List[str]:
    """CSV 字符串 → 去空白 token 列表（不去重、不丢空项，空项由调用方校验）。"""
    s = str(value or '').strip()
    if not s:
        return []
    return [t.strip() for t in s.split(',')]


def dedupe_keep_order(tokens: List[Any]) -> List[Any]:
    """去重保序（目录 id / 扩展名 / 类型数字列表通用；保留首现，任意可哈希元素）。"""
    return list(dict.fromkeys(t for t in tokens if t))


# ──────────────────────────── 入参校验 ────────────────────────────

#: --type 词形 → 数字（0 综合=不传 --type；公共库 build_search_file_param_v3 收 List[int]）
_VALID_FILE_TYPES = {
    'image': 1, 'audio': 2, 'video': 3, 'doc': 4, 'folder': 5, 'other': 6,
}
#: dynamic --type 受限取值（image=图片动态 / audio=音频动态 / video=视频动态 / doc=文档动态；缺省=全部文件动态）
_VALID_DYNAMIC_TYPES = {'image': 1, 'audio': 2, 'video': 3, 'doc': 4}
#: --time-field 合法枚举
_VALID_TIME_FIELDS = ('createdAt', 'updatedAt', 'takenAt')
#: --kind 合法枚举 → dynamicType（1 查看动态 / 2 上传动态）
_VALID_KINDS = {'view': 1, 'upload': 2}
#: --mode 合法枚举（view=单页快速返回；full=全量拉取+落盘+断点续传）
_VALID_MODES = ('view', 'full')
#: scope 列表上限（服务端约束）
_SCOPE_MAX = 20
#: 语义信号词——单字（docs/cli_design.md §10 单一来源；命中任一 → 非纯名词形态）
_SEMANTIC_SIGNAL_CHARS = '的在拍找看有时中上和与或及了着过是去来里'
#: 语义信号词——词（同上）
_SEMANTIC_SIGNAL_WORDS = ('照片', '图片', '截图', '视频', '附近', '最近')
#: 纯名词形态长度上限（--query strip 后字符数）
_PURE_NOUN_QUERY_MAX_LEN = 8


def _parse_mode(raw: str) -> str:
    """校验 ``--mode`` 词形：view / full，非法值报自然语言错（原始字符串入参）。"""
    mode = str(raw or '').strip().lower()
    if mode not in _VALID_MODES:
        raise CliValidationError(
            f'参数错误：--mode 仅支持 view（单页快速返回）或 full（全量拉取+落盘）；'
            f'当前传的是 {raw!r}。'
        )
    return mode


def _now_14() -> str:
    """实时当前时间（14 位 ``yyyyMMddHHmmss``，本地时区）。

    ``--end-at`` 省略时的缺省值与时间上限校验的共同基准；独立成函数便于测试冻结。
    """
    return datetime.now().strftime('%Y%m%d%H%M%S')


def _enforce_time_ceiling(
    start_14: str, end_14: str, start_raw: str, end_raw: str
) -> str:
    """时间上限处理（search/dynamic 共用）：start 超前报错，end 超前截断为当前时间。

    未来时间没有历史文件：start 超前整窗无意义——报错；end 超前截断为当前
    时间并打 stdout 提示行（含生效绝对值，断点续跑固定窗口以它为准）。
    返回生效的 14 位 end。extract 本函数避免两子命令口径漂移（戒律 12）。
    """
    now = _now_14()
    if start_14 > now:
        raise CliValidationError(
            f'参数错误：--start-at（{start_raw}）超过当前时间'
            f'（{format_datetime19(now)}）；未来时间没有历史文件，'
            '请把起点调到当前时间以内。'
        )
    if end_14 > now:
        write_cli_output_line(
            f'提示：--end-at（{end_raw}）超过当前时间，'
            f'已截断为 {format_datetime19(now)}；重跑请使用截断后的绝对时间。'
        )
        return now
    return end_14


@dataclass(frozen=True)
class DynamicArgs:
    """dynamic 子命令规范化入参（时间窗为归一化后的绝对值，保证重跑 digest 一致）。"""

    start_at: str  # yyyy-MM-dd HH:mm:ss
    end_at: str    # yyyy-MM-dd HH:mm:ss
    keyword: str
    dynamic_type: int
    content_type: Optional[int] = None  # None=全部文件动态(FileDynamic, 不下发) / 1=图片动态 / 4=文档动态
    mode: str = 'view'                  # view=单页快速返回 / full=全量拉取+落盘


@dataclass(frozen=True)
class FileFilters:
    """search 共用的结构化过滤参数（type/ext/time/size）。
    """

    type_list: List[int] = field(default_factory=list)
    ext_list: List[str] = field(default_factory=list)
    start_at: Optional[str] = None  # 14 位 yyyyMMddHHmmss
    end_at: Optional[str] = None    # 14 位 yyyyMMddHHmmss
    time_field: str = 'updatedAt'
    size_min: Optional[int] = None
    size_max: Optional[int] = None


@dataclass(frozen=True)
class SearchArgs:
    """检索子命令规范化入参（search 条件检索 / semantic-search 语义搜图共用）。

    query 仅 semantic-search 传入（语义搜索文本），search 恒 None；
    keyword 仅 search 传入。
    """

    query: Optional[str]           # 语义搜索文本；None=非语义（条件检索）
    keyword: str                   # 文件名/标题关键字（可空=纯条件筛选）
    mode: str = 'view'             # view=单页快速返回 / full=全量拉取+落盘
    type_list: List[int] = field(default_factory=list)
    ext_list: List[str] = field(default_factory=list)
    start_at: Optional[str] = None  # 14 位 yyyyMMddHHmmss
    end_at: Optional[str] = None    # 14 位 yyyyMMddHHmmss
    time_field: str = 'updatedAt'
    size_min: Optional[int] = None
    size_max: Optional[int] = None
    scope_in: List[str] = field(default_factory=list)
    scope_out: List[str] = field(default_factory=list)
    backup_folder_names: Optional[List[str]] = None  # None=不限定备份口径；否则为白名单内口径名列表
    recursive: Optional[bool] = None  # None=不递归（默认）；True=递归全部子目录
    keyword_hint: bool = False     # --query 纯名词形态提示标记（仅语义模式可能 True，非阻断）


def _is_pure_noun_query(query: str) -> bool:
    """纯名词形态判定：strip 后长度 ≤8、不含空白字符、不含语义信号词。

    非校验不 raise——只产出提示标记（误判无副作用：不改路由不阻断）；
    信号词表以 docs/cli_design.md §10 为单一来源。
    """
    text = str(query).strip()
    if not text or len(text) > _PURE_NOUN_QUERY_MAX_LEN:
        return False
    if any(ch.isspace() for ch in text):
        return False
    if any(ch in _SEMANTIC_SIGNAL_CHARS for ch in text):
        return False
    return not any(word in text for word in _SEMANTIC_SIGNAL_WORDS)


def validate_dynamic(ns: argparse.Namespace) -> DynamicArgs:
    """校验 dynamic 子命令：时间窗必填、绝对值、起止合法，--kind/--mode 枚举，--type 受限取值。"""
    kind_raw = str(ns.kind or 'view').strip().lower()
    if kind_raw not in _VALID_KINDS:
        raise CliValidationError(
            '参数错误：--kind 仅支持 view（查看动态）或 upload（上传动态）；'
            f'当前传的是 {ns.kind!r}。'
        )
    mode = _parse_mode(str(getattr(ns, 'mode', 'view') or 'view'))

    # --type 受限取值：image/audio/video/doc（均走 merge 端点，见 param_build）；缺省=全部文件动态
    type_raw = str(getattr(ns, 'type', '') or '').strip().lower()
    if type_raw:
        tokens = [t.strip() for t in type_raw.split(',') if t.strip()]
        if len(tokens) != 1:
            raise CliValidationError(
                '参数错误：--type 仅支持 image/audio/video/doc（或不传=全部文件动态），不支持多选；'
                '请只保留其中一个，或不传 --type 搜全部文件动态。'
            )
        token = tokens[0]
        if token not in _VALID_DYNAMIC_TYPES:
            raise CliValidationError(
                '参数错误：--type 仅支持 image/audio/video/doc（或不传=全部文件动态）；'
                '目录与其他类型暂不支持。'
            )
        content_type = _VALID_DYNAMIC_TYPES[token]
    else:
        content_type = None

    start_raw, end_raw = str(ns.start_at or '').strip(), str(ns.end_at or '').strip()
    if not start_raw:
        raise CliValidationError(
            '参数错误：dynamic 搜索必须提供 --start-at（绝对时间，'
            '如 "2026-08-01 00:00:00"；--end-at 可省略=自动取当前时间；'
            '用户说「最近一周」时请把起点换算成绝对时间）。'
        )

    # 日期简写补全为该日 00:00:00（与 references/SEARCH-DYNAMIC.md 一致）；
    # --end-at 省略 → 实时当前时间
    try:
        start_14 = parse_time_14(start_raw, end=False)
        end_14 = parse_time_14(end_raw, end=False) if end_raw else _now_14()
    except ValueError as exc:
        raise CliValidationError(f'参数错误：{exc}') from exc
    end_14 = _enforce_time_ceiling(start_14, end_14, start_raw, end_raw)
    if start_14 > end_14:
        raise CliValidationError(
            f'参数错误：--start-at（{start_raw}）不能晚于 --end-at（{end_raw}）；请调整时间范围。'
        )

    return DynamicArgs(
        start_at=format_datetime19(start_14),
        end_at=format_datetime19(end_14),
        keyword=str(ns.keyword or '').strip(),
        dynamic_type=_VALID_KINDS[kind_raw],
        content_type=content_type,
        mode=mode,
    )


def _parse_type_words(raw: str) -> List[int]:
    """解析 search --type 词形 CSV 为去重后的数字列表（内部仍用数字）。

    词形 → 数字：image=1 / audio=2 / video=3 / doc=4 / folder=5 / other=6。
    0 综合=不传 --type；非法词形报自然语言错（公共库 build_search_file_param_v3 收 List[int]）。
    """
    tokens = parse_csv_tokens(raw)
    if not tokens:
        return []
    types: List[int] = []
    for token in tokens:
        key = token.strip().lower()
        if key not in _VALID_FILE_TYPES:
            raise CliValidationError(
                f'参数错误：--type 含无法识别的值 {token!r}；'
                '--type 仅支持 image/audio/video/doc/folder/other 的组合，如 image,doc。'
            )
        types.append(_VALID_FILE_TYPES[key])
    return dedupe_keep_order(types)  # 去重保序


def _parse_ext_list(raw: str) -> List[str]:
    """解析 --ext CSV：去前导 ``.``、转小写、去重。"""
    tokens = parse_csv_tokens(raw)
    if not tokens:
        return []
    exts: List[str] = []
    for token in tokens:
        ext = token.lstrip('.').lower()
        if not ext:
            raise CliValidationError(
                '参数错误：--ext 包含空项；请用逗号分隔扩展名，如 jpg,png（前导 . 可省）。'
            )
        exts.append(ext)
    return dedupe_keep_order(exts)


def _parse_scope(raw: str, label: str) -> List[str]:
    """解析 --scope-in / --scope-out 的 fileId CSV（≤20，去空项与重复）。"""
    tokens = parse_csv_tokens(raw)
    if not tokens:
        return []
    for token in tokens:
        if not token:
            raise CliValidationError(
                f'参数错误：{label} 包含空项；请用逗号分隔目录 id，如 id1,id2。'
            )
    ids = dedupe_keep_order(tokens)
    if len(ids) > _SCOPE_MAX:
        raise CliValidationError(
            f'参数错误：{label} 最多支持 {_SCOPE_MAX} 个目录 id（当前 {len(ids)} 个）；请删减后重试。'
        )
    return ids


def validate_search(ns: argparse.Namespace) -> SearchArgs:
    """校验 search 子命令：文件/图片条件检索（--keyword 可选，可与过滤参数组合）。

    - keyword 可空=纯条件筛选；过滤参数校验（类型枚举、takenAt 纯图片、
      size×目录、scope 互斥与 ≤20、--backup-folder 与 scope 系互斥、
      备份口径白名单、时间对合法）。
    - ``--mode``：view（默认，单页快速返回）/ full（全量拉取+落盘+断点续传）。
    - 语义搜图在 semantic-search 子命令（见 validate_semantic_search）。
    """
    mode = _parse_mode(str(getattr(ns, 'mode', 'view') or 'view'))
    keyword = str(getattr(ns, 'keyword', '') or '').strip()

    # ── 文件/图片条件检索（keyword 可空=纯条件筛选）──
    filters = _parse_file_filters(ns)

    # scope：互斥 + 各 ≤20
    scope_in = _parse_scope(str(ns.scope_in or '').strip(), '--scope-in')
    scope_out = _parse_scope(str(ns.scope_out or '').strip(), '--scope-out')
    if scope_in and scope_out:
        raise CliValidationError(
            '参数错误：--scope-in 与 --scope-out 互斥，只能传其中一个；请只保留需要的一个。'
        )

    # --backup-folder：与 scope 系互斥（口径预设与任意目录范围不并存）
    backup_folder_names = _parse_backup_folder_names(getattr(ns, 'backup_folder', None))
    if backup_folder_names and (scope_in or scope_out):
        conflict = '--scope-in' if scope_in else '--scope-out'
        raise CliValidationError(
            f'参数错误：--backup-folder 与 {conflict} 互斥；--backup-folder 限定备份口径目录，'
            f'{conflict} 限定任意目录范围，两者不并存，请只保留需要的一个。'
        )

    # --recursive：不做校验，宽容解析（true/1/yes → True；其余非空 → False；空/未传 → None）
    recursive_raw = str(getattr(ns, 'recursive', '') or '').strip().lower()
    recursive = recursive_raw in ('true', '1', 'yes') if recursive_raw else None

    return SearchArgs(
        query=None,
        keyword=keyword,
        mode=mode,
        type_list=filters.type_list,
        ext_list=filters.ext_list,
        start_at=filters.start_at,
        end_at=filters.end_at,
        time_field=filters.time_field,
        size_min=filters.size_min,
        size_max=filters.size_max,
        scope_in=scope_in,
        scope_out=scope_out,
        backup_folder_names=backup_folder_names,
        recursive=recursive,
    )


def validate_semantic_search(ns: argparse.Namespace) -> SearchArgs:
    """校验 semantic-search 子命令：语义搜图，仅 --query（必填）与 --mode。

    纯名词形态判定命中置 ``keyword_hint``（非阻断提示标记，不改路由不 raise）。
    """
    mode = _parse_mode(str(getattr(ns, 'mode', 'view') or 'view'))
    query = str(getattr(ns, 'query', '') or '').strip()
    if not query:
        raise CliValidationError(
            '参数错误：--query 必填：一句自然语言描述要找的图'
            '（如「海边日落时小孩奔跑的照片」）。'
        )
    return SearchArgs(query=query, keyword='', mode=mode, keyword_hint=_is_pure_noun_query(query))


def _parse_file_filters(ns: argparse.Namespace) -> FileFilters:
    """解析 search 的结构化过滤参数（type/ext/time/size）。

    校验项：--type 词形枚举、takenAt 纯图片、时间对合法、size×目录互斥、
    大小区间合法。失败抛 CliValidationError。提取为本函数避免两子命令各写
    一份而漂移（戒律 12）。
    """
    type_list = _parse_type_words(str(ns.type or '').strip())

    # 缺省随 --type：纯图片=takenAt（照片的自然时间），其余=updatedAt；
    # 不传 type 绝不默认 takenAt（会静默收窄查询范围）；显式传入完全按传入值
    time_field = str(ns.time_field or '').strip() or (
        'takenAt' if type_list == [1] else 'updatedAt'
    )
    if time_field not in _VALID_TIME_FIELDS:
        raise CliValidationError(
            f'参数错误：--time-field 仅支持 createdAt / updatedAt / takenAt；当前传的是 {ns.time_field!r}。'
        )
    # takenAt（拍摄时间）仅纯图片类型支持（type_list == [1]，即 --type image）
    if time_field == 'takenAt' and type_list != [1]:
        raise CliValidationError(
            '参数错误：--time-field takenAt 仅支持纯图片类型搜索；'
            '请改用 createdAt/updatedAt，或把 --type 设为 image。'
        )

    # 时间对：只传 start 合法（end 实时取当前时间）；只传 end 报错；
    # 起止合法 + start 不晚于当前 / end 超前截断为当前
    start_raw = str(ns.start_at or '').strip()
    end_raw = str(ns.end_at or '').strip()
    if end_raw and not start_raw:
        raise CliValidationError(
            '参数错误：不能只传 --end-at；请同时提供 --start-at，'
            '或省略 --end-at（自动取当前时间）。'
        )
    start_at = end_at = None
    if start_raw:
        try:
            # start 补 000000 / end 补 235959（与公共库 parse_date_range_value 语义一致）；
            # end 省略 → 实时当前时间（精确到秒，不做 235959 补全）
            start_at = parse_time_14(start_raw, end=False)
            end_at = parse_time_14(end_raw, end=True) if end_raw else _now_14()
        except ValueError as exc:
            raise CliValidationError(f'参数错误：{exc}') from exc
        end_at = _enforce_time_ceiling(start_at, end_at, start_raw, end_raw)
        if start_at > end_at:
            raise CliValidationError(
                f'参数错误：--start-at（{start_raw}）不能晚于 --end-at（{end_raw}）；请调整时间范围。'
            )

    # 大小：解析 + 与目录类型(5)互斥
    size_min = size_max = None
    size_raw_min = str(ns.size_min or '').strip()
    size_raw_max = str(ns.size_max or '').strip()
    try:
        size_min = parse_size_bytes(size_raw_min) if size_raw_min else None
        size_max = parse_size_bytes(size_raw_max) if size_raw_max else None
    except ValueError as exc:
        raise CliValidationError(f'参数错误：{exc}') from exc
    has_size = size_min is not None or size_max is not None
    if has_size and 5 in type_list:
        raise CliValidationError(
            '参数错误：--size-min/--size-max 不支持目录类型（--type folder）；'
            '请去掉大小条件，或把 --type 改为不含 folder 的类型。'
        )
    if size_min is not None and size_max is not None and size_min > size_max:
        raise CliValidationError(
            '参数错误：--size-min 不能大于 --size-max；请调整大小区间。'
        )

    return FileFilters(
        type_list=type_list,
        ext_list=_parse_ext_list(str(ns.ext or '').strip()),
        start_at=start_at,
        end_at=end_at,
        time_field=time_field,
        size_min=size_min,
        size_max=size_max,
    )


def _parse_backup_folder_names(raw_codes: Optional[list]) -> Optional[List[str]]:
    """解析 ``--backup-folder`` 多次传入的中文名列表。

    返回 None 表示不限定备份口径（不传 --backup-folder）；否则为去重保序的
    白名单内名称列表。非法名（不在 8 个口径内）抛 CliValidationError（自然语言修正提示，
    列出口径名供 agent 选择）。
    """
    if not raw_codes:
        return None
    seen: set = set()
    names: List[str] = []
    for raw in raw_codes:
        name = str(raw or '').strip()
        if not name:
            continue
        if name in seen:
            continue
        if not is_valid_backup_folder_name(name):
            catalog = '、'.join(BACKUP_SCOPE_ROOT_FOLDER_NAMES)
            raise CliValidationError(
                f'参数错误：--backup-folder {name!r} 不在备份口径目录清单内；'
                f'请改用以下之一（不传则不限定备份口径）：{catalog}。'
            )
        seen.add(name)
        names.append(name)
    return names or None


__all__ = [
    'validate_search',
    'validate_dynamic',
    'SearchArgs',
    'DynamicArgs',
    'FileFilters',
    'parse_time_14',
    'format_datetime19',
    'parse_size_bytes',
    'parse_csv_tokens',
    'dedupe_keep_order',
    'BACKUP_SCOPE_ROOT_FOLDER_NAMES',
    'is_valid_backup_folder_name',
]
