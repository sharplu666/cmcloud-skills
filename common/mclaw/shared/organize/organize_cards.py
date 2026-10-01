#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""organize 任务卡片输出共享 helper（submit / status / retry 共用）。

跨 skill 复用：任何调 photoOrganize（归档/相册/回忆故事）三接口的整理流程，
submit/status/retry 三阶段都可用本模块统一卡片决策与发射，避免各技能各写一份。

卡片名按 task_type 路由（对齐旧版 cm_cloud_organize ``receipts.TASK_TYPE_CARD``）：

  - task_type=1（drive，归档到个人云文件夹）→ ``:::filePathList``（行 ``{filePath,
    parentFileId, enablePathHighlight, button}``，取自 ``results[*].name/id``）
  - task_type=2（album，相册整理）→ ``:::albumList``（行 ``{index, name, albumId}``，
    取自 ``results[*].name/id``；空项跳过）
  - task_type=3（memory，回忆故事整理）→ ``:::memoryAlbum``（行同 albumList 结构）

非终态 / 异步提交 / 终态 results 为空 → 回落 ``:::taskList``（单行
``{taskid, type:"organize", organizeType, taskType}``）。终态全失败（4）→ 无卡。

卡片 meta.summary 文案（迁自旧技能 ``organize_card_copy``，submit/status/retry 共用）：
处理中 taskList 用 ``build_task_submitted_summary`` 三行提交文案；终态结果卡用
``build_result_summary`` 一句引导（hint 优先服务端回传 processingHint，fallback
``organize_task_name`` 任务类型名）。

设计戒律：
  - **必须**用公共库 ``emit_card_block`` / ``emit_file_path_list_card`` 发卡
    （自带 ``<frontend_card>`` 包裹 + 末行 meta + atexit 末尾说明），**禁止**手拼 ``:::xxx`` 围栏。
  - **results 项 name/id 空时跳过**（旧技能缺陷⑤修复经验：空项做成卡行=点不开的幽灵目录，
    且卡行数≠文本成功数）。
  - **禁止**在全失败（status=4）或 results 为空时发空结果卡——回落 taskList 保住查看入口。
  - **回执只给数据结构**：本模块发卡并返回卡片名（字符串），record 命名 / message 文案 /
    renderCards 回填留技能层。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mclaw.shared.cm_cloud.cli_cards import emit_card_block, emit_file_path_list_card
from mclaw.shared.organize.photo_organize_task import (
    TASK_TYPE_ALBUM,
    TASK_TYPE_DRIVE,
    TASK_TYPE_MEMORY,
    TaskSnapshot,
)

__all__ = [
    'ORGANIZE_TYPE_BY_TASK',
    'TASK_NAME_BY_TASK_TYPE',
    'TASK_TYPE_TO_CARD',
    'build_result_summary',
    'build_task_submitted_summary',
    'emit_card_for_snapshot',
    'organize_task_name',
]


#: task_type → 终态结果卡名（对齐旧版 cm_cloud_organize ``receipts.TASK_TYPE_CARD``）。
#: drive→filePathList（目录路径）/ album→albumList / memory→memoryAlbum。
TASK_TYPE_TO_CARD: Dict[int, str] = {
    TASK_TYPE_DRIVE: 'filePathList',
    TASK_TYPE_ALBUM: 'albumList',
    TASK_TYPE_MEMORY: 'memoryAlbum',
}

#: task_type → organizeType 字段值（taskList 卡行用）：drive='file'，album/memory='image'。
ORGANIZE_TYPE_BY_TASK: Dict[int, str] = {
    TASK_TYPE_DRIVE: 'file',
    TASK_TYPE_ALBUM: 'image',
    TASK_TYPE_MEMORY: 'image',
}

#: drive 终态结果卡的「去查看」按钮文案（与旧技能 ``organize_card_copy.VIEW_BUTTON`` 对齐）
_VIEW_BUTTON = '去查看 >'

#: task_type → 整理任务类型名（提交卡/结果卡文案变量；迁自旧技能 organize_card_copy）
TASK_NAME_BY_TASK_TYPE: Dict[int, str] = {
    TASK_TYPE_DRIVE: '整理到个人云文件夹',
    TASK_TYPE_ALBUM: '相册整理',
    TASK_TYPE_MEMORY: '回忆故事整理',
}


def organize_task_name(task_type: int) -> str:
    """task_type → 固定整理任务类型名（1 整理到个人云文件夹 / 2 相册整理 / 3 回忆故事整理）。

    未知值（快照缺字段/0）兜底「整理任务」，不编造目标标签——发卡路径不得因缺字段中断。
    """
    return TASK_NAME_BY_TASK_TYPE.get(int(task_type or 0), '整理任务')


def build_task_submitted_summary(
    task_name: str, processing_hint: Optional[str] = None
) -> str:
    """提交卡（taskList）三行固定文案：任务名后附 processingHint（有则括号，无则原样）。"""
    hint = str(processing_hint or '').strip()
    title = f'{task_name}（{hint}）' if hint else str(task_name or '')
    return ' \n '.join([
        f'{title}，整理任务已提交！',
        'MClaw 已开始为您整理，需要等待一段时间，请耐心等候',
        '任务完成后会自动通知您，届时可查看整理结果。您可以点击「查看详情」按钮，查看实时进度',
    ])


def build_result_summary(
    task_type: int, processing_hint: Optional[str] = None
) -> str:
    """终态结果卡一句引导：hint 优先，无则回落任务类型名。"""
    hint = str(processing_hint or '').strip()
    if not hint:
        hint = organize_task_name(task_type=task_type)
    return f'点击卡片查看为您整理好的 {hint}'


def _resolve_organize_type(task_type: int) -> str:
    """task_type → organizeType：drive=1 → 'file'，album/memory → 'image'。"""
    return ORGANIZE_TYPE_BY_TASK.get(int(task_type or 0), 'file')


def _build_file_path_rows(results: List[Any]) -> List[Dict[str, Any]]:
    """从 ``results`` 构造 ``:::filePathList`` 行（drive 终态）。

    入参 ``results`` 为公共库类型化的结果项列表（``TaskSnapshot.results`` /
    ``SubmitResult.results``）。每项取 ``.id`` → ``parentFileId``、``.name`` → ``filePath``，
    附 ``enablePathHighlight=True`` + ``button='去查看 >'``。``name`` 为空跳过。
    """
    rows: List[Dict[str, Any]] = []
    for item in results or []:
        name = str(getattr(item, 'name', '') or '').strip()
        if not name:
            continue
        parent_id = str(getattr(item, 'id', '') or '').strip()
        rows.append({
            'filePath': name,
            'parentFileId': parent_id,
            'enablePathHighlight': True,
            'button': _VIEW_BUTTON,
        })
    return rows


def _build_album_rows(results: List[Any]) -> List[Dict[str, Any]]:
    """从 ``results`` 构造 ``:::albumList`` / ``:::memoryAlbum`` 行（album/memory 终态）。

    行字段 ``{index, name, albumId}``（对齐旧版 cm_cloud_organize ``receipts._build_result_card_rows``
    的 album/memory 分支）：``albumId`` ← ``results[*].id``（相册 id / 故事 id），
    ``name`` ← ``results[*].name``（相册名 / 故事名）。``name`` 与 ``albumId`` 均空时跳过
    （旧技能缺陷⑤修复经验：空项不做卡行）。``index`` 为 1-based 仅计存活行。
    """
    rows: List[Dict[str, Any]] = []
    index = 0
    for item in results or []:
        name = str(getattr(item, 'name', '') or '').strip()
        album_id = str(getattr(item, 'id', '') or '').strip()
        if not (name or album_id):
            continue
        index += 1
        rows.append({'index': index, 'name': name, 'albumId': album_id})
    return rows


def _emit_result_card(
    task_type: int,
    results: List[Any],
    *,
    summary: Optional[str] = None,
) -> Optional[str]:
    """发射终态结果卡，返回卡片名；无可发卡行返回 ``None``（调用方回落 taskList）。

    - drive（1）→ ``:::filePathList``，经 ``emit_file_path_list_card``（rows 空不发卡返回 None）。
    - album（2）→ ``:::albumList``；memory（3）→ ``:::memoryAlbum``，经 ``emit_card_block``。
      rows 空不发卡返回 None（禁止发空结果卡误导用户）。
    """
    card_name = TASK_TYPE_TO_CARD.get(int(task_type or 0))
    if not card_name:
        return None
    if task_type == TASK_TYPE_DRIVE:
        rows = _build_file_path_rows(results)
        if not rows:
            return None
        emit_file_path_list_card(rows, cli='photoOrganize', summary=summary)
        return 'filePathList'
    rows = _build_album_rows(results)
    if not rows:
        return None
    emit_card_block(card_name, None, rows, cli='photoOrganize', count=len(rows), summary=summary)
    return card_name


def _emit_task_list_card(
    task_id: str,
    *,
    task_type: int,
    organize_type: str,
    summary: Optional[str] = None,
) -> str:
    """发射 ``:::taskList`` 卡片块，返回卡片名 ``'taskList'``。

    taskList 行字段对齐旧技能：``taskid``（非 taskId）/ ``type="organize"`` /
    ``organizeType`` / ``taskType``（字符串化）。header 为 ``None``（taskList 无 loadMore 首行）。
    用于异步（task_info None）/ 非终态（status 1/2）/ 终态 results 为空回落。
    """
    rows: List[Dict[str, Any]] = [{
        'taskid': str(task_id or '').strip(),
        'type': 'organize',
        'organizeType': str(organize_type or '').strip(),
        'taskType': str(int(task_type or 0)),
    }]
    emit_card_block('taskList', None, rows, cli='photoOrganize', count=1, summary=summary)
    return 'taskList'


def emit_card_for_snapshot(
    snap: Optional[TaskSnapshot] = None,
    *,
    task_id: str = '',
    task_type: Optional[int] = None,
    results: Optional[List[Any]] = None,
    organize_type: Optional[str] = None,
    processing_hint: str = '',
) -> Optional[str]:
    """卡片决策矩阵（submit/status/retry 共用），发射卡片并返回卡片名。

    统一状态→卡片路由，避免三处 service 各写一份决策分支：

    - ``snap`` 为 None（异步，仅 submit/retry 可能）→ ``:::taskList``
    - 非终态（status 1/2 处理中）→ ``:::taskList``
    - 终态成功/部分成功（3/5）且 ``results`` 非空 → 按 task_type 取结果卡
      （drive→filePathList / album→albumList / memory→memoryAlbum）
    - 终态成功/部分成功（3/5）但 ``results`` 为空 → 回落 ``:::taskList``
      （大任务服务端只回计数无 results；旧技能缺陷⑤修复经验：禁止发空结果卡）
    - 终态全失败（4）→ 无卡（``None``），由 ``message`` 文本承载

    卡片 meta.summary 由 ``processing_hint`` 驱动：处理中 taskList 卡用
    ``build_task_submitted_summary`` 三行提交文案（3.1）；终态结果卡与回落
    taskList 用 ``build_result_summary`` 一句引导（3.2）。``snap`` 非 None 时
    hint 优先取 ``snap.processing_hint``（服务端回传），否则取入参。

    Args:
        snap: ``TaskSnapshot``；submit/retry 异步时传 None。
        task_id: 任务 id（``snap`` 为 None 时必填，用于 taskList 行）。
        task_type: 任务类型（1 drive / 2 album / 3 memory）。``snap`` 非 None 时取
            ``snap.task_type``；``snap`` 为 None（异步提交）时由调用方显式传入——
            album/memory 异步提交需正确的 task_type 才能渲染对 organizeType 与
            （终态时）正确的结果卡名，**不能缺省 drive**。
        results: 终态结果项列表（submit 用 ``SubmitResult.results``，status/retry
            用 ``snap.results``）。``snap`` 非 None 时缺省取 ``snap.results``。
        organize_type: organizeType（submit 从 plan header 读；status/retry 由 task_type
            推导）。缺省时由 task_type 推导；``snap`` 与 ``task_type`` 均无时缺省 drive='file'。
        processing_hint: 整理任务名提示（提交卡/结果卡文案变量）。submit 异步传
            本地 ``--processing-hint``；``snap`` 回传的 ``processing_hint`` 优先于此入参。

    Returns:
        卡片名（``'filePathList'`` / ``'albumList'`` / ``'memoryAlbum'`` / ``'taskList'``）
        或 ``None``（无卡）。
    """
    if snap is None:
        # 异步：发 :::taskList（task_type 由调用方传入；缺省 drive 兼容旧调用点）
        tt = int(task_type or TASK_TYPE_DRIVE)
        org_type = organize_type or _resolve_organize_type(tt)
        summary = build_task_submitted_summary(
            organize_task_name(task_type=tt), processing_hint=processing_hint,
        )
        return _emit_task_list_card(
            task_id, task_type=tt, organize_type=org_type, summary=summary,
        )

    tt = int(getattr(snap, 'task_type', 0) or task_type or TASK_TYPE_DRIVE)
    org_type = organize_type or _resolve_organize_type(tt)
    results_list = results if results is not None else list(getattr(snap, 'results', []) or [])
    snap_task_id = str(getattr(snap, 'task_id', '') or task_id)
    snap_hint = str(getattr(snap, 'processing_hint', '') or '').strip() or str(processing_hint or '').strip()

    if not bool(getattr(snap, 'is_terminal', False)):
        # 非终态（1/2）：taskList + 三行提交文案
        summary = build_task_submitted_summary(
            organize_task_name(task_type=tt), processing_hint=snap_hint,
        )
        return _emit_task_list_card(
            snap_task_id, task_type=tt, organize_type=org_type, summary=summary,
        )

    status = int(getattr(snap, 'status', 0) or 0)
    if status in (3, 5):
        # 终态成功/部分成功：按 task_type 发结果卡；空 results → 回落 taskList
        summary = build_result_summary(task_type=tt, processing_hint=snap_hint)
        emitted = _emit_result_card(tt, results_list, summary=summary)
        if emitted:
            return emitted
        return _emit_task_list_card(
            snap_task_id, task_type=tt, organize_type=org_type, summary=summary,
        )
    # status==4 全失败：无卡
    return None
