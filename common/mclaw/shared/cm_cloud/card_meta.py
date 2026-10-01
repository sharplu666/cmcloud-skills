#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""卡片围栏末行 ``meta.resultType`` / ``meta.summary`` —— 按 CLI 子命令配置。

**改本文件 ``CARD_META_BY_CLI`` 即可全局生效**，无需改各业务脚本。

结构（推荐）::

    CLI子命令名 → {
        'resultType': 'search' | 'generate',   # 本 CLI 默认类型（可配）
        '卡片名': 'summary模板',                 # 继承 resultType
        '另一卡': ('generate', '文案'),         # 单卡可覆盖 resultType
    }

- ``resultType``：仅 ``search`` / ``generate``
- ``summary``：可用 ``{n}`` 占位条数；空串表示不写 summary 字段
- 搜索列表卡精选文案见 ``SEARCH_LIST_SUMMARY``（``{n}`` / ``{shown}`` / ``{bucket}``），由 ``build_search_result_summary`` 选用；规划精选/去重传 ``phase='plan'``；``--dedup`` 未精选用 ``*.dedup`` / ``*.dedup.plan``
- 仅一张卡时也可简写为 ``(resultType, summary)`` 元组

用法::

    from mclaw.shared.cm_cloud.card_meta import resolve_card_meta, format_card_meta_jsonl

    meta = resolve_card_meta(cli='search_note', card='noteList', count=12)
    line = format_card_meta_jsonl(cli='publish_circle', card='groupPath')
"""

from __future__ import annotations

import atexit
import sys

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from mclaw.utils.settings import CardSetting

RESULT_TYPE_SEARCH = 'search'
RESULT_TYPE_GENERATE = 'generate'

_CLI_RESULT_TYPE_KEY = 'resultType'

# (resultType, summary_template)
_Spec = Tuple[str, str]
# 单卡简写 / 多卡配置
_CliEntry = Union[_Spec, Dict[str, Union[str, _Spec]]]

# 搜索列表卡（manage / organize 共用）：默认命中 / 精选 / 分桶精选
# 精选默认「搜索结果」；规划阶段用 ``*.plan`` 变体。
SEARCH_LIST_SUMMARY: Dict[str, str] = {
    'imageList': '为您找到{n}张图片',
    'fileList': '为您找到{n}个内容',
    'imageList.dedup': '已从搜索结果中去重得到{n}张图片，优先展示{shown}张图片',
    'fileList.dedup': '已从搜索结果中去重得到{n}个文件，优先展示{shown}个文件',
    'imageList.select': '已从搜索结果中精选出{n}张图片，优先展示{shown}张图片',
    'fileList.select': '已从搜索结果中精选出{n}个内容，优先展示{shown}个内容',
    'imageList.bucket': '已从搜索结果中（{bucket}分类）精选出{n}张图片，优先展示{shown}张图片',
    'fileList.bucket': '已从搜索结果中（{bucket}分类）精选出{n}个内容，优先展示{shown}个内容',
    'imageList.select.plan': '已从规划结果中精选出{n}张图片，优先展示{shown}张图片',
    'fileList.select.plan': '已从规划结果中精选出{n}个内容，优先展示{shown}个内容',
    'imageList.bucket.plan': '已从规划结果中（{bucket}分类）精选出{n}张图片，优先展示{shown}张图片',
    'fileList.bucket.plan': '已从规划结果中（{bucket}分类）精选出{n}个内容，优先展示{shown}个内容',
    'imageList.dedup.plan': '已从规划结果中去重得到{n}张图片，优先展示{shown}张图片',
    'fileList.dedup.plan': '已从规划结果中去重得到{n}个文件，优先展示{shown}个文件',
}


def _search_list_card_entries(*, image: bool = True, file: bool = True) -> Dict[str, str]:
    """搜索 CLI 的 imageList/fileList，指向 SEARCH_LIST_SUMMARY 默认命中文案。"""
    out: Dict[str, str] = {}
    if image:
        out['imageList'] = SEARCH_LIST_SUMMARY['imageList']
    if file:
        out['fileList'] = SEARCH_LIST_SUMMARY['fileList']
    return out


# ---------------------------------------------------------------------------
# ★ 按 CLI 子命令配置（改这里全局生效）
# ---------------------------------------------------------------------------
CARD_META_BY_CLI: Dict[str, _CliEntry] = {
    # —— 云笔记 ——
    'search_note': {
        'resultType': RESULT_TYPE_SEARCH,
        'noteList': '为您找到{n}个笔记',
    },
    'note_list': {
        'resultType': RESULT_TYPE_SEARCH,
        'noteList': '为您找到{n}个笔记',
    },
    'audio_note_list': {
        'resultType': RESULT_TYPE_SEARCH,
        'noteList': '为您找到{n}个笔记',
    },
    # —— 链接分享 ——
    'share_search_subscription': {
        'resultType': RESULT_TYPE_SEARCH,
        'shareSubscriptionList': '已为您找到{n}个订阅更新',
    },
    'share_search_file': {
        'resultType': RESULT_TYPE_SEARCH,
        'shareSubscriptionList': '已为您找到{n}个分享',
    },
    'share_wechat': {
        'resultType': RESULT_TYPE_GENERATE,
        'button': '已为您生成微信分享',
    },
    'share_save_updates': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您转存{n}个文件',
        'filePathList': '已为您整理成{n}个文件夹',
    },
    'share_outerlink_batch_task': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您转存{n}个文件',
        'filePathList': '已为您整理成{n}个文件夹',
    },
    # —— 群组 ——
    'publish_circle': {
        'resultType': RESULT_TYPE_GENERATE,
        'groupPath': '已为您发布到',
    },
    # —— 图文搜人 ——
    'person_search': {
        'resultType': RESULT_TYPE_SEARCH,
        'selectFaceList': (RESULT_TYPE_GENERATE, '请选择要搜索的人物'),
        'imageList': SEARCH_LIST_SUMMARY['imageList'],
    },
    # —— 知识库 ——
    'search_kbs': {
        'resultType': RESULT_TYPE_SEARCH,
        'knowledgeBaseList': '已为您找到{n}个知识库',
    },
    'search_resources': {
        'resultType': RESULT_TYPE_SEARCH,
        'knowledgeBaseFile': '已为您找到{n}个知识库文件',
    },
    'rag_search': {
        'resultType': RESULT_TYPE_SEARCH,
        'knowledgeBaseReference': '为您找到{n}条知识库参考内容',
    },
    'list_contents': {
        'resultType': RESULT_TYPE_SEARCH,
        'knowledgeBaseFile': '为您找到{n}项知识库内容',
    },
    'resource_batch_get': {
        'resultType': RESULT_TYPE_SEARCH,
        'knowledgeBaseFile': '为您找到{n}项知识库内容',
    },
    'upload_file': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提供上传目录入口',
    },
    'upload_cloud_file': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提供上传目录入口',
    },
    'folder_create': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提供新建目录入口',
    },
    'resource_update': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提供资源所在目录入口',
    },
    'import_url': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提交网页导入任务',
    },
    'batch_import': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提交批量导入任务',
    },
    'resource_batch_move': {
        'resultType': RESULT_TYPE_GENERATE,
        'knowledgeBasePath': '已为您提交资源移动任务',
    },
    'share_friend': {
        'resultType': RESULT_TYPE_GENERATE,
        'contacts': '已为您完成好友分享',
    },
    # —— 阅读记录 ——
    'find_reading': {
        'resultType': RESULT_TYPE_SEARCH,
        'bookList': '为您找到{n}本图书',
    },
    # —— 相册 ——
    'search_album': {
        'resultType': RESULT_TYPE_SEARCH,
        'albumList': '已为您找到{n}个相册',
        'memoryAlbum': '已为您找到{n}个回忆故事',
    },
    'album_add': {
        'resultType': RESULT_TYPE_GENERATE,
        'albumList': '已为您保存到相簿',
    },
    'custom_file_add': {
        'resultType': RESULT_TYPE_GENERATE,
        'albumList': '已为您添加到相簿',
    },
    'custom_update': {
        'resultType': RESULT_TYPE_GENERATE,
        'albumList': '已为您更新自定义内容到相簿',
    },
    'story_add': {
        'resultType': RESULT_TYPE_GENERATE,
        'memoryAlbum': '已为您生成回忆故事',
    },
    'story_update': {
        'resultType': RESULT_TYPE_GENERATE,
        'memoryAlbum': '已为您生成回忆故事',
    },
    'story_playlist_add': {
        'resultType': RESULT_TYPE_GENERATE,
        'memoryAlbum': '已为您生成回忆故事列表',
    },
    # —— 个人云 manage ——
    'search_keyword': {
        'resultType': RESULT_TYPE_SEARCH,
        **_search_list_card_entries(),
    },
    'search_filter': {
        'resultType': RESULT_TYPE_SEARCH,
        **_search_list_card_entries(),
    },
    'search_backup': {
        'resultType': RESULT_TYPE_SEARCH,
        **_search_list_card_entries(),
    },
    'search_image': {
        'resultType': RESULT_TYPE_SEARCH,
        **_search_list_card_entries(file=False),
    },
    'list': {
        'resultType': RESULT_TYPE_SEARCH,
        **_search_list_card_entries(image=False),
    },
    'upload': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您上传{n}个内容',
        'filePathList': '已为您上传到{n}个文件夹',
    },
    'batch_move': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您移动{n}个内容',
        'filePathList': '已为您移动到{n}个文件夹',
    },
    'batch_copy': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您复制{n}个内容',
        'filePathList': '已为您复制到{n}个文件夹',
    },
    'batch_rename': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您重命名{n}个内容',
        'filePathList': '已为您重命名到{n}个文件夹',
    },
    'batch_check_exists': {
        'resultType': RESULT_TYPE_GENERATE,
        'fileList': '已为您处理{n}个内容',
    },
    # —— 个人动态（单入口脚本，按卡片区分）——
    'query_personal_dynamic': {
        'resultType': RESULT_TYPE_SEARCH,
        **_search_list_card_entries(),
        'videoList': '为您找到{n}个视频',
        'audioList': '为您找到{n}个音频',
        'shareSubscriptionList': '已为您找到{n}个订阅更新',
        'dynamicList': '为您找到{n}个动态',
    },
    # —— AI 生视频 ——
    # confirmButton：确认文案在卡片 text（promptCopy）；sendText 为确认话术+任务参数分段；meta.summary 为空。
    # taskList：预计等待文案在卡片 text；meta 仅 resultType=search、summary 为空。
    'ai_video_estimate': {
        'resultType': RESULT_TYPE_GENERATE,
        'confirmButton': '',
    },
    'ai_video_create': {
        'resultType': RESULT_TYPE_SEARCH,
        'taskList': '',
    },
    'ai_video_query': {
        'resultType': RESULT_TYPE_GENERATE,
        'aiVideoPath': '',
        'bigVideoList': '',
    },
    # —— 云盘整理 ——
    # photoOrganize 终态/提交卡的 summary 由 organize_cards（build_*_summary）动态覆盖；
    # 此处为兜底模板。
    'photoOrganize': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您整理成{n}个文件夹',
        'albumList': '已为您保存到相簿',
        'memoryAlbum': '已为您生成回忆故事',
        'taskList': (RESULT_TYPE_SEARCH, '已为您提交{n}个整理任务'),
        'imageList': (RESULT_TYPE_SEARCH, '为您精选到{n}张图片，优先展示10张图片'),
        'fileList': (RESULT_TYPE_SEARCH, SEARCH_LIST_SUMMARY['fileList']),
    },
    'photoOrganize_prepare': {
        'resultType': RESULT_TYPE_SEARCH,
        'imageList': '已为您筛选到{n}张图片，准备开始处理',
        'fileList': '已为您筛选到{n}个文件，准备开始处理',
        'albumList': '已为您筛选到{n}个相簿，准备开始处理',
        'memoryAlbum': '已为您筛选到{n}个回忆故事，准备开始处理',
    },
    # —— 修图 / 生图类（各 skill CLI 名；文案相同可并列）——
    'ai_retouch': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'text_to_image': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'ai_image_generate': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'image_edit_save': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您处理{n}张图片',
    },
    'human_matting': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'image_enhance': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'old_photo_restore': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'image_comic_style': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'image_shift': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'live_photo': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'ai_expand_image': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'ai_avatar': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'baby_time_machine': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
    'baby_face_prediction': {
        'resultType': RESULT_TYPE_GENERATE,
        'filePathList': '已为您保存结果',
        'bigImageList': '已为您生成{n}张图片',
    },
}

_DEFAULT_SPEC: _Spec = (RESULT_TYPE_SEARCH, '')


@dataclass(frozen=True)
class CardMetaResolved:
    result_type: str
    summary: str
    extra: Dict[str, Any]


def _normalize_spec(raw: Any) -> Optional[_Spec]:
    if (
        isinstance(raw, tuple)
        and len(raw) == 2
        and isinstance(raw[0], str)
        and isinstance(raw[1], str)
    ):
        return raw[0], raw[1]
    return None


def _cli_default_result_type(entry: Dict[str, Any]) -> str:
    rt = entry.get(_CLI_RESULT_TYPE_KEY, RESULT_TYPE_SEARCH)
    return str(rt or RESULT_TYPE_SEARCH)


def _card_entries(entry: Dict[str, Any]) -> Dict[str, Union[str, _Spec]]:
    return {
        key: val
        for key, val in entry.items()
        if key != _CLI_RESULT_TYPE_KEY
    }


def _validate_result_type(value: str, *, context: str) -> str:
    rt = str(value or '').strip()
    if rt not in (RESULT_TYPE_SEARCH, RESULT_TYPE_GENERATE):
        raise ValueError(
            f'{context}: resultType 仅支持 '
            f'{RESULT_TYPE_SEARCH!r}/{RESULT_TYPE_GENERATE!r}，收到 {value!r}'
        )
    return rt


def _lookup_spec(cli: str, card: str) -> _Spec:
    entry = CARD_META_BY_CLI.get(str(cli or '').strip())
    if entry is None:
        return _DEFAULT_SPEC
    flat = _normalize_spec(entry)
    if flat is not None:
        return _validate_result_type(flat[0], context=f'CARD_META_BY_CLI[{cli!r}]'), flat[1]
    if isinstance(entry, dict):
        default_rt = _validate_result_type(
            _cli_default_result_type(entry),
            context=f'CARD_META_BY_CLI[{cli!r}].resultType',
        )
        cards = _card_entries(entry)
        card_key = str(card or '').strip()
        if card_key in cards:
            raw = cards[card_key]
            spec = _normalize_spec(raw)
            if spec is not None:
                return (
                    _validate_result_type(spec[0], context=f'CARD_META_BY_CLI[{cli!r}].{card_key}'),
                    spec[1],
                )
            if isinstance(raw, str):
                return default_rt, raw
        # 仅当未传 card 且只配了一张卡时可用该卡；传了错误卡名绝不吞掉
        if not card_key and len(cards) == 1:
            only_name, only_raw = next(iter(cards.items()))
            spec = _normalize_spec(only_raw)
            if spec is not None:
                return (
                    _validate_result_type(
                        spec[0],
                        context=f'CARD_META_BY_CLI[{cli!r}].{only_name}',
                    ),
                    spec[1],
                )
            if isinstance(only_raw, str):
                return default_rt, only_raw
    return _DEFAULT_SPEC


def format_card_summary(
    template: str,
    *,
    count: Optional[int] = None,
    shown: Optional[int] = None,
    bucket: Optional[str] = None,
) -> str:
    text = str(template or '')
    if not text:
        return ''
    mapping = {
        'n': int(count or 0),
        'shown': int(shown if shown is not None else 0),
        'bucket': str(bucket or ''),
    }
    try:
        return text.format(**mapping)
    except (KeyError, ValueError, IndexError):
        if '{n}' in text:
            return text.format(n=int(count or 0))
        return text


def build_search_result_summary(
    *,
    file_type: str = 'image',
    total: int = 0,
    shown: int = 0,
    top: int = 0,
    bucket_name: Optional[str] = None,
    phase: Optional[str] = None,
    dedup: bool = False,
) -> str:
    """搜索/规划预览卡 ``meta.summary``（manage / organize 共用）。

    模板取自 ``SEARCH_LIST_SUMMARY``：

    - 未传 ``--top`` 且无桶名：``为您找到{n}张图片/个内容``
    - ``--dedup`` 且未精选：``已从搜索结果中去重得到{n}张图片/个文件，优先展示{shown}…``
    - 精选（``top>0`` 或有桶名）默认：``已从搜索结果中…精选出{n}…，优先展示{shown}…``
    - ``phase='plan'``：``已从规划结果中…``（去重为 ``*.dedup.plan``）
    - 有 ``bucket_name`` 时插入 ``（{bucket}分类）``
    """
    kind = str(file_type or '').strip().lower()
    card = 'imageList' if kind in ('image', 'imagelist') else 'fileList'
    bucket = str(bucket_name).strip() if bucket_name is not None else ''
    phase_key = str(phase or '').strip().lower()
    if not bucket and int(top or 0) <= 0:
        if dedup:
            key = f'{card}.dedup.plan' if phase_key == 'plan' else f'{card}.dedup'
        else:
            key = card
    else:
        base = f'{card}.bucket' if bucket else f'{card}.select'
        key = f'{base}.plan' if phase_key == 'plan' else base
    return format_card_summary(
        SEARCH_LIST_SUMMARY[key],
        count=total,
        shown=shown,
        bucket=bucket,
    )


def resolve_card_meta(
    *,
    cli: str,
    card: str = '',
    count: Optional[int] = None,
    result_type: Optional[str] = None,
    summary: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> CardMetaResolved:
    """按 CLI 子命令 + 卡片名解析 resultType / summary。"""
    resolved_rt, template = _lookup_spec(cli, card)
    if result_type is not None:
        resolved_rt = _validate_result_type(
            str(result_type),
            context='resolve_card_meta(result_type=...)',
        )
    else:
        resolved_rt = _validate_result_type(
            resolved_rt,
            context=f'resolve_card_meta(cli={cli!r}, card={card!r})',
        )
    if summary is None:
        summary_text = format_card_summary(template, count=count)
    else:
        summary_text = str(summary)
    return CardMetaResolved(
        result_type=resolved_rt,
        summary=summary_text,
        extra=dict(extra or {}),
    )


def card_meta_line_payload(
    *,
    cli: str,
    card: str = '',
    count: Optional[int] = None,
    result_type: Optional[str] = None,
    summary: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    resolved = resolve_card_meta(
        cli=cli,
        card=card,
        count=count,
        result_type=result_type,
        summary=summary,
        extra=extra,
    )
    meta_extra = dict(resolved.extra)
    if resolved.summary:
        meta_extra['summary'] = resolved.summary
    return {
        'result_type': resolved.result_type,
        'extra': meta_extra or None,
    }


def format_card_meta_jsonl(
    *,
    cli: str,
    card: str = '',
    count: Optional[int] = None,
    result_type: Optional[str] = None,
    summary: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> str:
    """直接返回围栏末行 JSON 字符串。"""
    from mclaw.shared.organize.preview_cards import card_result_meta_line

    payload = card_meta_line_payload(
        cli=cli,
        card=card,
        count=count,
        result_type=result_type,
        summary=summary,
        extra=extra,
    )
    return card_result_meta_line(payload['result_type'], extra=payload['extra'])


# ---------------------------------------------------------------------------
# ★ Agent 防复述：frontend_card 包裹 + toolresult 末尾 agent_note
# ---------------------------------------------------------------------------
# 卡片围栏（:::xxxList）仅供前端插件解析渲染；模型读到 toolresult 后可能在
# 文字回复中复述围栏格式导致严重错误。做法：
#
# 1. 每张卡输出时用 ``<frontend_card name="...">...</frontend_card>`` 包裹
#    （``frontend_card_tags``），给模型明确的数据块边界；
# 2. 输出结束（``cli_timing.flush_cli_output_buffer`` 末尾，或进程退出兜底）
#    追加 ``<agent_note>``（``card_end_note``），声明全部卡片已由前端渲染、
#    回复须为纯文本。
#
# 标签与说明文案配置见 ``mclaw.utils.settings.CardSetting``。
_card_registry: List[Dict[str, str]] = []
_end_note_emitted = False
_atexit_registered = False


def frontend_card_tags(*, card: str) -> Tuple[str, str]:
    """返回 (开标签, 闭标签) 供调用方包裹一张卡；同时登记卡片名供末尾说明枚举。"""
    global _atexit_registered
    name = str(card or '').strip()
    if not name:
        return '', ''
    _card_registry.append({'card': name})
    if not _atexit_registered:
        atexit.register(_emit_end_note_at_exit)
        _atexit_registered = True
    return (
        CardSetting.FRONTEND_CARD_OPEN_TMPL.format(card=name),
        CardSetting.FRONTEND_CARD_CLOSE,
    )


def card_end_note() -> str:
    """toolresult 末尾的 ``<agent_note>``；无登记或已发过时返回 ''。"""
    global _end_note_emitted
    if _end_note_emitted or not _card_registry:
        return ''
    _end_note_emitted = True
    names = '、'.join(dict.fromkeys(item['card'] for item in _card_registry))
    return '\n'.join(
        line.format(names=names) for line in CardSetting.CARD_END_NOTE_LINES
    )


def _emit_end_note_at_exit() -> None:
    """进程退出兜底：未经 flush 的直写路径（receipts/裸 print）也能拿到末尾说明。"""
    if 'pytest' in sys.modules:
        return
    note = card_end_note()
    if not note:
        return
    try:
        import cli_timing
    except ImportError:
        print(note, flush=True)
        return
    if cli_timing.is_cli_output_buffering():
        # 脚本忘了 flush：并入缓冲并强制刷出，避免连卡片输出一起丢失
        cli_timing.write_cli_output_line(note)
        cli_timing.flush_cli_output_buffer()
    else:
        print(note, flush=True)


__all__ = [
    'RESULT_TYPE_SEARCH',
    'RESULT_TYPE_GENERATE',
    'CARD_META_BY_CLI',
    'SEARCH_LIST_SUMMARY',
    'CardMetaResolved',
    'build_search_result_summary',
    'format_card_summary',
    'resolve_card_meta',
    'card_meta_line_payload',
    'format_card_meta_jsonl',
    'frontend_card_tags',
    'card_end_note',
]
