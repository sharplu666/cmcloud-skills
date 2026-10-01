#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一卡片生成与校验（``Card`` 类 + 24 类 schema 注册表）。

``Card.generate()`` 是唯一卡片组装点：复用公共库原语组装围栏块，``cardId`` 仍由
``preview_cards.card_result_meta_line`` 无条件注入（**本类不重写 cardId 生成**）。
``Card.validate()`` 按 ``CARD_SPECS`` 每类 schema 校验结构 / meta 不变式 / 行字段。

调用方标准写法::

    write_card_lines(Card('fileList', rows=rows, header=h, cli='upload').generate())

入参与 ``card_emit.emit_card_block`` 对齐（``card_name``→``card_type``），便于迁移。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mclaw.shared.cm_cloud.card_meta import card_meta_line_payload, frontend_card_tags

try:
    from cli_timing import write_cli_output_line
except ImportError:  # 测试环境无 cli_timing 时回落 print，避免导入失败
    def write_cli_output_line(line: str) -> None:
        print(line, flush=True)


RESULT_TYPE_SEARCH = 'search'
RESULT_TYPE_GENERATE = 'generate'
_VALID_RESULT_TYPES = (RESULT_TYPE_SEARCH, RESULT_TYPE_GENERATE)


@dataclass(frozen=True)
class CardSpec:
    """单类卡片的格式 schema（``CARD_SPECS`` 条目）。

    - ``has_loadmore``：是否支持 loadMore 首行（True=可有可无；False=header 须为 None）。
    - ``uses_index``：数据行是否应含 ``index`` 字段。
    - ``required_row_fields``：每行必填字段（validate 强制存在）。
    - ``optional_row_fields``：条件输出字段（仅登记，不强制存在，避免误报）。
    - ``allowed_meta_extra``：允许的 meta 额外键（除 resultType/summary/cardId）；当前仅登记。
    """

    card_name: str
    has_loadmore: bool
    uses_index: bool
    required_row_fields: Tuple[str, ...]
    optional_row_fields: Tuple[str, ...] = ()
    allowed_meta_extra: Tuple[str, ...] = ()


#: 24 类卡片 schema，按 ``docs/card_format_spec.md`` §3 字段表核对。条件输出字段一律进
#: ``optional_row_fields``（如 knowledgeBaseReference 的 shardingList、filePathList 的
#: fileCount/pretext、button 的 schemeType、taskList 的 organizeType/taskType/text/fileId）。
CARD_SPECS: Dict[str, CardSpec] = {
    'fileList': CardSpec(
        'fileList', True, True,
        ('name', 'fileId', 'size', 'category', 'fileExtension'),
        ('duration', 'contentSchedule', 'autoRun'),
    ),
    'imageList': CardSpec(
        'imageList', True, True,
        ('name', 'fileId', 'size', 'category', 'fileExtension'),
    ),
    'videoList': CardSpec(
        'videoList', True, True,
        ('fileId', 'name', 'size', 'fileExtension', 'category'),
        ('duration', 'contentSchedule', 'autoRun'),
    ),
    'audioList': CardSpec(
        'audioList', True, True,
        ('fileId', 'name', 'fileExtension', 'category', 'size'),
        ('contentSchedule', 'autoRun'),
    ),
    'dynamicList': CardSpec(
        'dynamicList', False, False,
        ('dynamicId', 'dynamicType', 'fileId', 'parentFileId', 'parentFileName', 'fileName',
         'size', 'sizeByte', 'category', 'fileExtension', 'shareTime', 'shareText'),
        ('contentSchedule', 'duration'),
    ),
    'bookList': CardSpec(
        'bookList', False, False,
        ('bookId', 'contentId', 'name', 'bookType', 'chapterId', 'chapterOffset'),
        ('title',),
    ),
    'albumList': CardSpec(
        'albumList', False, True,
        ('name', 'albumId'),
        ('renderCard', 'subtitle'),
    ),
    'memoryAlbum': CardSpec(
        'memoryAlbum', False, True,
        ('name', 'albumId'),
        ('renderCard', 'subtitle'),
    ),
    'noteList': CardSpec(
        'noteList', True, True,
        ('noteId', 'title'),
    ),
    'shareSubscriptionList': CardSpec(
        'shareSubscriptionList', True, True,
        ('linkName', 'shareTime', 'shareText', 'expireTime', 'linkId', 'passwd'),
    ),
    'contacts': CardSpec(
        'contacts', False, False,
        ('userName', 'phoneNumber'),
    ),
    'button': CardSpec(
        'button', False, False,
        ('autoRun', 'autoRunCopy', 'buttonCopy', 'runType', 'params'),
        ('schemeType',),
    ),
    'taskList': CardSpec(
        'taskList', False, False,
        ('taskid', 'type'),
        ('organizeType', 'taskType', 'text', 'fileId'),
    ),
    'confirmButton': CardSpec(
        'confirmButton', False, False,
        ('type', 'text', 'sendText'),
    ),
    'bigImageList': CardSpec(
        'bigImageList', False, False,
        ('fileId',),
    ),
    'aiVideoPath': CardSpec(
        'aiVideoPath', False, False,
        ('text', 'button'),
    ),
    'bigVideoList': CardSpec(
        'bigVideoList', False, False,
        ('fileId', 'fileName', 'fileSize', 'fileExtension', 'category', 'duration', 'contentSchedule', 'type'),
    ),
    'filePathList': CardSpec(
        'filePathList', False, False,
        ('filePath', 'parentFileId'),
        ('enablePathHighlight', 'button', 'pretext', 'fileCount'),
        ('shownByButton',),
    ),
    'groupPath': CardSpec(
        'groupPath', False, False,
        ('groupId', 'groupName', 'button', 'pretext'),
    ),
    'knowledgeBaseFile': CardSpec(
        'knowledgeBaseFile', True, False,
        ('resourceId', 'name', 'baseName', 'baseId'),
    ),
    'knowledgeBaseReference': CardSpec(
        'knowledgeBaseReference', False, False,
        ('resource', 'baseName'),
        ('shardingList', 'highlightShardingList'),
    ),
    'knowledgeBasePath': CardSpec(
        'knowledgeBasePath', False, False,
        ('baseId', 'baseName', 'folderId', 'folderName', 'button', 'pretext'),
    ),
    'knowledgeBaseList': CardSpec(
        'knowledgeBaseList', True, True,
        ('baseId', 'name', 'baseType', 'openLevel', 'totalCount', 'isJoined', 'photoId'),
        ('memberCount', 'description'),
    ),
    'selectFaceList': CardSpec(
        'selectFaceList', False, False,
        ('fileId', 'name', 'text'),
    ),
}


@dataclass
class ValidationResult:
    """``Card.validate()`` 返回值。"""

    ok: bool
    errors: List[str] = field(default_factory=list)


class Card:
    """统一卡片生成器：按 ``card_type`` 组装围栏块 + 校验格式。

    ``generate()`` 只返回各行，写入 stdout 由调用方经 ``write_card_lines`` 负责。
    ``cardId`` 由公共库 ``card_result_meta_line`` 注入，本类不碰。
    """

    __slots__ = (
        'card_type', 'rows', 'cli', 'header', 'count', 'result_type', 'summary', 'extra_meta',
    )

    def __init__(
        self,
        card_type: str,
        rows: List[Dict[str, Any]],
        *,
        cli: str = '',
        header: Optional[Dict[str, Any]] = None,
        count: Optional[int] = None,
        result_type: Optional[str] = None,
        summary: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.card_type = str(card_type or '').strip()
        self.rows = list(rows or [])
        self.cli = str(cli or '').strip()
        self.header = header
        self.count = count
        self.result_type = result_type
        self.summary = summary
        self.extra_meta = extra_meta

    def generate(self) -> List[str]:
        """生成卡片全部 stdout 行（frontend_card 包裹 + 围栏 + 行 + meta），不写 stdout。

        复用 ``card_meta_line_payload``（解析 resultType/summary）、``frontend_card_tags``
        （取标签、保留登记副作用供 agent_note）、``card_result_meta_line``（注入 cardId）。
        """
        from mclaw.shared.organize.preview_cards import card_result_meta_line

        effective_count = self.count if self.count is not None else len(self.rows)
        payload = card_meta_line_payload(
            cli=self.cli,
            card=self.card_type,
            count=effective_count,
            result_type=self.result_type,
            summary=self.summary,
            extra=self.extra_meta,
        )
        open_tag, close_tag = frontend_card_tags(card=self.card_type)

        lines: List[str] = []
        if open_tag:
            lines.append(open_tag)
        lines.append(f':::{self.card_type}')
        if self.header is not None:
            lines.append(json.dumps(self.header, ensure_ascii=False))
        for row in self.rows:
            lines.append(json.dumps(row, ensure_ascii=False))
        lines.append(card_result_meta_line(payload['result_type'], extra=payload['extra']))
        lines.append(':::')
        if close_tag:
            lines.append(close_tag)
        return lines

    def validate(self) -> ValidationResult:
        """校验卡片格式：结构 + meta 不变式 + 每类行字段 schema。"""
        errors: List[str] = []
        spec = CARD_SPECS.get(self.card_type)
        if spec is None:
            return ValidationResult(False, [f'未知卡片类型: {self.card_type!r}'])

        # 1. loadMore 应有性：不支持的卡 header 必须为 None
        if not spec.has_loadmore and self.header is not None:
            errors.append(f'{self.card_type}: 不支持 loadMore 首行，但传了 header')

        # 2. index 应有性 + 行字段 schema（行经 json.dumps 直出，校验输入行即校验输出行）
        for i, row in enumerate(self.rows, start=1):
            if not isinstance(row, dict):
                errors.append(f'{self.card_type}: 第{i}行非 dict')
                continue
            if spec.uses_index and 'index' not in row:
                errors.append(f'{self.card_type}: 第{i}行缺 index')
            if not spec.uses_index and 'index' in row:
                errors.append(f'{self.card_type}: 第{i}行不应含 index')
            for name in spec.required_row_fields:
                if name not in row:
                    errors.append(f'{self.card_type}: 第{i}行缺必填字段 {name}')

        # 3. 结构 + meta 不变式：从 generate() 取产物校验
        try:
            lines = self.generate()
        except ValueError as exc:  # resultType 非法等会让 card_result_meta_line 抛错
            errors.append(f'{self.card_type}: 生成失败 {exc}')
            return ValidationResult(not errors, errors)

        if self.card_type:
            if not lines or lines[0] != f'<frontend_card name="{self.card_type}">':
                errors.append(f'{self.card_type}: 缺 frontend_card 开标签')
            if len(lines) < 2 or lines[1] != f':::{self.card_type}':
                errors.append(f'{self.card_type}: 缺 ::: 围栏开行')
            if not lines or lines[-1] != '</frontend_card>':
                errors.append(f'{self.card_type}: 缺 frontend_card 闭标签')
            if len(lines) < 2 or lines[-2] != ':::':
                errors.append(f'{self.card_type}: 缺 ::: 围栏闭行')

        meta_obj = self._meta_from_lines(lines)
        if meta_obj is None:
            errors.append(f'{self.card_type}: 未找到 meta 行')
        else:
            rt = meta_obj.get('resultType')
            if rt not in _VALID_RESULT_TYPES:
                errors.append(f'{self.card_type}: resultType 非法 {rt!r}')
            cid = meta_obj.get('cardId')
            if not (isinstance(cid, str) and re.fullmatch(r'\d{7}', cid)):
                errors.append(f'{self.card_type}: cardId 非法 {cid!r}')
            keys = list(meta_obj)
            if keys and keys[-1] != 'cardId':
                errors.append(f'{self.card_type}: cardId 非末键')

        return ValidationResult(not errors, errors)

    @staticmethod
    def _meta_from_lines(lines: List[str]) -> Optional[Dict[str, Any]]:
        """从卡片各行中取出末行 meta 对象（``{"meta": {...}}`` 的 ``meta`` 值）。"""
        for line in lines:
            if not line or line[0] != '{':
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict) and isinstance(obj.get('meta'), dict):
                return obj['meta']
        return None


def write_card_lines(lines: List[str]) -> None:
    """将 ``Card.generate()`` 返回的行逐行写入 stdout（经 ``write_cli_output_line`` 缓冲）。"""
    for line in lines:
        write_cli_output_line(line)


__all__ = [
    'Card',
    'CardSpec',
    'CARD_SPECS',
    'ValidationResult',
    'write_card_lines',
    'RESULT_TYPE_SEARCH',
    'RESULT_TYPE_GENERATE',
]
