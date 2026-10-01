#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 图片处理 skills 共享工具模块（shared 层）。

仅承载**纯工具函数与业务编排输出逻辑**：
  - ``build_url`` / ``generate_source_task_id`` / ``TASK_STATUS_TEXT``：纯工具
  - ``extract_poll_result``：从 dispatcher 返回的 ``AsyncPollResponse`` 提取状态与 fileUrlList
  - ``handle_sub_result_output``：轮询结果输出处理（通过注入的 dispatcher 查询 namePath）

**不发 HTTP、不持鉴权/host**。所有 HTTP 调用通过调用方注入的
``dispatcher: ApiDispatcher`` 完成（属性链 ``d.<namespace>.<leaf>(req)``）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from mclaw.api.personal_saas.get_path_api import GetPathRequest

try:
    from cli_timing import write_cli_output_line
except ImportError:
    def write_cli_output_line(line: str) -> None:
        print(line, flush=True)


__all__ = [
    'TASK_STATUS_TEXT',
    'build_url',
    'generate_source_task_id',
    'extract_poll_result',
    'handle_sub_result_output',
    'emit_file_path_list_card',
    'emit_big_image_list_card',
]


# ──────────────────────────── 公共常量 ────────────────────────────

TASK_STATUS_TEXT = {
    1: '待处理',
    2: '处理中',
    3: '任务成功',
    4: '任务失败',
    5: '已过期',
}


# ──────────────────────────── 基础工具函数 ────────────────────────────


def build_url(host: str, path: str) -> str:
    """拼接 host 和 API 路径为完整 URL。"""
    return host.rstrip('/') + '/' + path.lstrip('/')


def generate_source_task_id() -> int:
    """基于当前时间生成毫秒级 sourceTaskId。"""
    return int(time.time() * 1000)


# ──────────────────────────── 轮询结果提取 ────────────────────────────


def extract_poll_result(poll_response: Any) -> Dict[str, Any]:
    """从 dispatcher 返回的 ``AsyncPollResponse`` 提取状态、taskId 和 fileUrlList。

    Args:
        poll_response: ``ApiDispatcher`` 异步 API 返回的 ``AsyncPollResponse`` 对象，
            含 ``status`` / ``status_text`` / ``task_id`` / ``file_url_list`` 字段。

    Returns:
        ``{"status": int, "statusText": str, "taskId": str, "fileUrlList": List[str]}``
    """
    return {
        'status': poll_response.status,
        'statusText': TASK_STATUS_TEXT.get(poll_response.status, '未知状态'),
        'taskId': poll_response.task_id,
        'fileUrlList': list(poll_response.file_url_list or []),
    }


# ──────────────────────────── 渲染卡直出 ────────────────────────────


def emit_file_path_list_card(
    file_path: str,
    parent_file_id: str,
    *,
    pretext: str = '点击去查看:',
    button: str = '去查看',
    cli: str = '',
) -> None:
    """直出 ``:::filePathList``「去查看」回执卡（render_format:432-456）。

    通常在写操作（上传/移动/另存）完成后、``:::bigImageList`` 之前输出，
    指向结果文件所在的目录。

    Args:
        file_path: 目录展示路径（namePath）。
        parent_file_id: 目录 fileId（文件夹为自身 fileId）。
        pretext: 按钮前提示文案，不需要时传空字符串。
        button: 按钮文案，例如"去查看"；不需要时传空字符串。
        cli: CLI / skill 名，用于 card_meta 查表。
    """
    from mclaw.shared.cm_cloud.card import Card

    row = {
        'filePath': file_path,
        'parentFileId': parent_file_id,
        'enablePathHighlight': True,
        'pretext': pretext,
        'button': button,
    }
    for line in Card(
        'filePathList', [row], cli=cli, count=1, extra_meta={'shownByButton': False}
    ).generate():
        write_cli_output_line(line)


def emit_big_image_list_card(file_ids: List[str], *, cli: str = '') -> None:
    """直出 ``:::bigImageList`` 结果图卡片。

    Args:
        file_ids: 结果文件 fileId 列表；多张则在 ``:::bigImageList`` 与 ``:::``
            之间拼接多份，每行一个 ``{"fileId": "..."}``。
        cli: CLI / skill 名，用于 card_meta 查表。
    """
    from mclaw.shared.cm_cloud.card import Card

    rows = [{'fileId': fid} for fid in file_ids]
    for line in Card('bigImageList', rows, cli=cli, count=len(rows)).generate():
        write_cli_output_line(line)


# ──────────────────────────── 轮询结果输出处理 ────────────────────────────


def handle_sub_result_output(
    poll_response: Any,
    base64_output_dir: str,
    dispatcher: Any,
    yun_dir: str = None,
    *,
    cli: str = '',
) -> None:
    """处理轮询结果，优先读取 fileInfoList 并输出文件信息；回退到 subResultType 处理。

    Args:
        poll_response: ``ApiDispatcher`` 异步 API 返回的 ``AsyncPollResponse`` 对象。
            本函数从 ``poll_response.raw`` 读取原始 ``data.resultList`` 嵌套结构。
        base64_output_dir: base64 图片落盘目录（subResultType=2 分支使用）。
        dispatcher: 调用方注入的 ``ApiDispatcher``，用于查询 fileInfoList 中各 fileId
            的 namePath（``dispatcher.personal_saas.get_path``）。
        yun_dir: 保留参数，当前未使用。
    """
    raw = getattr(poll_response, 'raw', None) or {}
    data = raw.get('data') or {}
    task_id = str(data.get('taskId')) if data.get('taskId') is not None else None
    handled = False
    for item in data.get('resultList') or []:
        if not isinstance(item, dict):
            continue

        # 优先读取 fileInfoList
        file_info_list = item.get('fileInfoList')
        if isinstance(file_info_list, list) and file_info_list:
            fids = [
                info.get('fileId')
                for info in file_info_list
                if isinstance(info, dict) and info.get('fileId')
            ]
            path_map: Dict[str, str] = {}
            if fids:
                path_resp = dispatcher.personal_saas.get_path(
                    GetPathRequest(file_ids=fids)
                )
                path_map = {it.file_id: it.name_path for it in path_resp.ok_items}

            if fids and cli:
                parent_id = ''
                dir_path = ''
                for info in file_info_list:
                    if not isinstance(info, dict):
                        continue
                    parent_id = str(info.get('parentFileId') or '').strip()
                    if parent_id:
                        break
                name_path = path_map.get(fids[0], '')
                if name_path and '/' in name_path:
                    dir_path = name_path.rsplit('/', 1)[0]
                elif name_path:
                    dir_path = name_path
                if parent_id and dir_path:
                    emit_file_path_list_card(dir_path, parent_id, cli=cli)
                emit_big_image_list_card(fids, cli=cli)
                handled = True
                continue

            write_cli_output_line('=' * 5)
            write_cli_output_line('最终结果如下所示，每一行代表一个结果：')
            for info in file_info_list:
                if not isinstance(info, dict):
                    continue
                fid = info.get('fileId')
                output = {
                    'name': info.get('name'),
                    'fileId': fid,
                    'namePath': path_map.get(fid, ''),
                    'size': info.get('size'),
                    'category': info.get('category'),
                    'fileExtension': info.get('fileExtension'),
                    'check_success': '<img src=',
                }
                write_cli_output_line(json.dumps(output, ensure_ascii=False))
            write_cli_output_line('=' * 5)
            handled = True
            continue

        # 回退：按 subResultType 处理
        sub_result_type = _extract_sub_result_type(item)
        if sub_result_type is None:
            continue

        if sub_result_type == 1:
            file_url_list = [u for u in (item.get('fileUrlList') or []) if isinstance(u, str)]
            write_cli_output_line(''.join([f'<img src="{url}">' for url in file_url_list]))
            handled = True
            continue

        if sub_result_type == 2:
            base64_values: List[str] = []
            for key in ('fileUrlList', 'base64List'):
                value = item.get(key)
                if isinstance(value, list):
                    base64_values.extend([x for x in value if isinstance(x, str)])
            content_value = item.get('content')
            if isinstance(content_value, str):
                base64_values.append(content_value)
            filtered_values = []
            for text in base64_values:
                stripped = text.strip()
                if stripped.startswith('http://') or stripped.startswith('https://'):
                    continue
                filtered_values.append(stripped)
            if not filtered_values:
                raise RuntimeError('subResultType=2 但未找到可用的 base64 图片数据')
            saved = _save_base64_images(filtered_values, base64_output_dir, task_id)
            for path in saved:
                write_cli_output_line(f'已将图片保存到{path}路径')
            handled = True
            continue

        if sub_result_type == 3:
            write_cli_output_line('这是文件信息列表：')
            write_cli_output_line(json.dumps(item.get('fileInfoList') or [], ensure_ascii=False, indent=2))
            handled = True
            continue

    if not handled:
        write_cli_output_line('未识别到可处理的 fileInfoList 或 subResultType（1/2/3）。')


# ──────────────────────────── 内部工具（仅 handle_sub_result_output 用） ────────────────────────────


def _extract_sub_result_type(item: Dict[str, Any]) -> Optional[int]:
    """从结果项中提取 subResultType 字段并转为整数。"""
    value = item.get('subResultType')
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _save_base64_images(
    base64_list: List[str],
    output_dir: str,
    task_id: Optional[str],
) -> List[str]:
    """将 base64 图片列表保存到本地文件，返回保存路径列表。"""
    import base64
    from pathlib import Path

    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: List[str] = []
    prefix = task_id or 'task'
    for idx, base64_text in enumerate(base64_list, start=1):
        ext = _resolve_base64_ext(base64_text)
        file_path = out_dir / f'{prefix}_{idx}.{ext}'
        file_path.write_bytes(_decode_base64_image(base64_text))
        saved_paths.append(str(file_path))
    return saved_paths


def _decode_base64_image(base64_text: str) -> bytes:
    """解码 base64 图片数据，支持 data URI 格式。"""
    import base64

    raw = base64_text.strip()
    if ',' in raw and raw.split(',', 1)[0].startswith('data:'):
        raw = raw.split(',', 1)[1]
    return base64.b64decode(raw, validate=True)


def _resolve_base64_ext(base64_text: str) -> str:
    """从 base64 字符串（含 data URI 前缀）推断图片扩展名。"""
    raw = base64_text.strip()
    if raw.startswith('data:image/') and ';base64,' in raw:
        ext = raw.split('data:image/', 1)[1].split(';', 1)[0].strip().lower()
        if ext in {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}:
            return 'jpg' if ext == 'jpeg' else ext
    return 'png'
