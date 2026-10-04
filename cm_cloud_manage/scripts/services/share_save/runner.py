#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""share-save / share-download 编排：列分享 → 转存 →（可选）下载到本地。"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

from mclaw.shared.cm_cloud.cli_jsonl import emit_jsonl
from mclaw.shared.cm_cloud.folder_ops import ensure_folder_path_parts
from mclaw.shared.postprocess.cli_rows import format_bytes
from mclaw.shared.postprocess.paths import join_cloud_dir_path, split_cloud_dir_path

from services.atomic.client import api_batch_download_url, api_check_exists
from services.atomic.file_lookup import get_file_path_map
from services.share_save.args import ShareRef, parse_share_input, resolve_passwd
from services.share_save.client import (
    ShareApiError,
    ShareItem,
    get_session_account,
    list_share_tree,
    save_share,
)
from services.stdout_receipt import error_meta
from utils.config import EXIT_BUSINESS_ERROR, EXIT_OK

SAVE_POLL_TIMEOUT = 600  # 转存任务轮询总超时（秒）：服务端为异步批量任务，大文件/排队时需更久
SAVE_POLL_INTERVAL = 10  # 轮询间隔（秒）


class ShareSaveError(Exception):
    """转存流程业务错误（参数/前置条件类）。"""


@dataclass
class ResolvedNode:
    kind: str  # 'file' | 'folder'
    name: str
    rel: Tuple[str, ...]  # 相对 target_dir 的路径元组（不含自身名）
    drive_file_id: str = ''
    size: int = 0
    status: str = ''  # saved | existed | pending（任务已提交，轮询超时仍未确认落盘）
    children: List['ResolvedNode'] = field(default_factory=list)


@dataclass
class SaveResult:
    share_name: str
    link_id: str
    target_id: str
    target_path: str
    task_id: str
    nodes: List[ResolvedNode] = field(default_factory=list)
    direct: bool = False  # True=分享者为本账号，免转存直取

    @property
    def saved_count(self) -> int:
        return sum(1 for n in self.nodes if n.status == 'saved')

    @property
    def existed_count(self) -> int:
        return sum(1 for n in self.nodes if n.status == 'existed')

    @property
    def pending_count(self) -> int:
        return sum(1 for n in self.nodes if n.status == 'pending')



def _resolve_target_dir(target_dir: Optional[str], session_str: str) -> Tuple[str, str]:
    """解析转存目标目录，返回 (catalog_id, 云盘路径)。"""
    from session_folder import ensure_default_session_upload_parent

    target = (target_dir or '').strip()
    if not target:
        folder_id, full_path = ensure_default_session_upload_parent(
            session_str, error_cls=ShareSaveError
        )
        return str(folder_id), str(full_path)
    if target.startswith('/'):
        parts = split_cloud_dir_path(target)
        if not parts:
            raise ShareSaveError('目标云盘目录不能为空')
        try:
            folder = ensure_folder_path_parts(parts, error_cls=ShareSaveError)
        except ShareSaveError:
            raise
        except Exception as e:
            raise ShareSaveError(f'目标目录创建/解析失败: {e}')
        folder_id = str(folder.get('fileId') or '').strip()
        if not folder_id:
            raise ShareSaveError(f'目标目录 {target} 未返回 fileId')
        return folder_id, join_cloud_dir_path(parts)
    # 视为目录 fileId
    path_map = get_file_path_map([target], action='分享转存') or {}
    parent_path = str(path_map.get(target) or '').strip()
    if not parent_path:
        raise ShareSaveError(f'目标目录 fileId 不存在：{target}')
    return target, parent_path


def _check_exists_id(parent_id: str, name: str) -> str:
    """存在返回 drive fileId，否则返回空串。"""
    try:
        row = api_check_exists(parent_id, name) or {}
    except Exception:
        return ''
    data = row.get('data') if isinstance(row.get('data'), dict) else {}
    if not data.get('exist'):
        return ''
    return str(data.get('appFileId') or '').strip()


def _do_save(
    share_text: str,
    passwd: Optional[str],
    target_dir: Optional[str],
    session_str: str,
    command: str,
) -> SaveResult:
    ref = parse_share_input(share_text)
    if not ref.link_id:
        raise ShareSaveError(
            '无法从输入中解析出分享 ID：请传入完整的 139 分享链接（yun.139.com/shareweb/#/w/i/…）或分享 ID'
        )
    pwd = resolve_passwd(passwd, ref)

    try:
        nodes, meta = list_share_tree(ref.link_id, pwd)
    except ShareApiError:
        raise
    if not nodes:
        raise ShareApiError('分享内容为空：该分享下没有任何文件', fatal=True)

    # 快路径：分享者就是当前登录账号 → 文件本就在自己云盘里，免转存，
    # 分享 contentID 可直接当 drive fileId 用（download 验证过）。
    try:
        account = get_session_account()
    except ShareApiError:
        account = ''
    if account and meta.get('creator') == account:
        def _direct(node: ShareItem, rel: Tuple[str, ...]) -> ResolvedNode:
            rn = ResolvedNode(
                kind=node.kind, name=node.name, rel=rel,
                drive_file_id=node.share_id, size=node.size, status='existed',
            )
            for child in node.children:
                rn.children.append(_direct(child, rel + (node.name,)))
            return rn

        return SaveResult(
            share_name=str(meta.get('shareName') or ''),
            link_id=ref.link_id,
            target_id='',
            target_path='',
            task_id='',
            nodes=[_direct(n, ()) for n in nodes],
            direct=True,
        )

    target_id, target_path = _resolve_target_dir(target_dir, session_str)

    # 快照：转存前目标目录下已存在的同名项（用于区分 saved / existed）
    pre_existing: Dict[str, str] = {}
    for n in nodes:
        fid = _check_exists_id(target_id, n.name)
        if fid:
            pre_existing[n.name] = fid

    file_paths = [n.share_path for n in nodes if n.kind == 'file']
    folder_paths = [n.share_path for n in nodes if n.kind == 'folder']
    task_id = save_share(ref.link_id, pwd, file_paths, folder_paths, target_id)

    # 轮询等待转存落盘
    deadline = time.monotonic() + SAVE_POLL_TIMEOUT
    found: Dict[str, str] = {}
    while time.monotonic() < deadline:
        pending = [n for n in nodes if n.name not in found]
        for n in pending:
            fid = _check_exists_id(target_id, n.name)
            if fid:
                found[n.name] = fid
        if len(found) == len(nodes):
            break
        time.sleep(SAVE_POLL_INTERVAL)

    def _resolve(node: ShareItem, parent_id: str, rel: Tuple[str, ...]) -> ResolvedNode:
        fid = found.get(node.name, '')
        if fid:
            status = 'existed' if pre_existing.get(node.name) == fid else 'saved'
        else:
            # 任务已提交但轮询超时仍未确认：标记 pending（非失败），可稍后复查
            status = 'pending'
        rn = ResolvedNode(
            kind=node.kind, name=node.name, rel=rel,
            drive_file_id=fid, size=node.size, status=status,
        )
        if node.kind == 'folder' and fid:
            for child in node.children:
                rn.children.append(_resolve(child, fid, rel + (node.name,)))
        elif node.kind == 'folder':
            for child in node.children:
                rn.children.append(_resolve(child, '', rel + (node.name,)))
        return rn

    resolved = [_resolve(n, target_id, ()) for n in nodes]
    return SaveResult(
        share_name=str(meta.get('shareName') or ''),
        link_id=ref.link_id,
        target_id=target_id,
        target_path=target_path,
        task_id=task_id,
        nodes=resolved,
    )


def _flatten_files(nodes: List[ResolvedNode]) -> List[ResolvedNode]:
    out: List[ResolvedNode] = []
    for n in nodes:
        if n.kind == 'file' and n.status in ('saved', 'existed') and n.drive_file_id:
            out.append(n)
        out.extend(_flatten_files(n.children))
    return out


def _download_nodes(
    files: List[ResolvedNode], download_dir: str
) -> Tuple[List[Dict[str, Any]], int, int]:
    """下载文件（保留分享内的相对目录结构）。返回 (results, ok_count, fail_count)。"""
    os.makedirs(download_dir, exist_ok=True)
    file_ids = [f.drive_file_id for f in files]
    try:
        urls = api_batch_download_url(file_ids) or {}
    except Exception as e:
        raise ShareSaveError(f'获取下载地址失败: {e}')

    results: List[Dict[str, Any]] = []
    tty = sys.stderr.isatty()
    for idx, node in enumerate(files, 1):
        rel_path = os.path.join(*node.rel, node.name) if node.rel else node.name
        local_path = os.path.join(download_dir, rel_path)
        url = urls.get(node.drive_file_id, '')
        if not url:
            results.append({
                'fileId': node.drive_file_id, 'fileName': node.name,
                'relPath': rel_path, 'status': 'error',
                'message': '未获取到下载地址', 'localPath': '',
            })
            continue
        try:
            os.makedirs(os.path.dirname(local_path) or download_dir, exist_ok=True)
            with requests.get(url, stream=True, timeout=300) as r:
                if r.status_code != 200:
                    raise RuntimeError(f'HTTP {r.status_code}')
                total = int(r.headers.get('Content-Length', '0') or 0)
                done = 0
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(256 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                if not tty:
                    sys.stderr.write(
                        f'[{idx}/{len(files)}] {rel_path}  完成  '
                        f'{format_bytes(done)}/{format_bytes(total)}\n'
                    )
                    sys.stderr.flush()
            results.append({
                'fileId': node.drive_file_id, 'fileName': node.name,
                'relPath': rel_path, 'status': 'success',
                'message': '下载成功', 'localPath': local_path,
            })
        except Exception as e:
            results.append({
                'fileId': node.drive_file_id, 'fileName': node.name,
                'relPath': rel_path, 'status': 'error',
                'message': str(e), 'localPath': '',
            })
    ok_count = sum(1 for r in results if r['status'] == 'success')
    return results, ok_count, len(results) - ok_count


def _emit_save_meta(command: str, result: SaveResult, phase: str = '') -> None:
    status = 'success' if result.pending_count == 0 else (
        'warning' if result.saved_count + result.existed_count > 0 else 'error'
    )
    meta: Dict[str, Any] = {
        'record': 'meta', 'command': command, 'status': status,
        'shareName': result.share_name, 'linkId': result.link_id,
        'targetDir': result.target_path, 'taskId': result.task_id,
        'totalCount': len(result.nodes),
        'savedCount': result.saved_count,
        'existedCount': result.existed_count,
        'pendingCount': result.pending_count,
    }
    if result.pending_count:
        meta['hint'] = (
            '转存任务已提交但部分项目超时未确认落盘；服务端任务仍在执行，'
            '可稍后用 batch_check_exists <目标目录fileId>:<名称> 复查'
        )
    if result.direct:
        meta['mode'] = 'direct'
        meta['note'] = '分享者为当前登录账号，文件本就在云盘中，跳过转存直接取用'
    if phase:
        meta['phase'] = phase
    emit_jsonl(meta)
    for idx, n in enumerate(result.nodes, 1):
        cloud_path = (
            (result.target_path.rstrip('/') + '/' + n.name) if result.target_path and n.drive_file_id
            else ('/（本账号分享，云盘原有）' if result.direct and n.drive_file_id else '')
        )
        emit_jsonl({
            'record': 'result', 'index': idx,
            'kind': n.kind, 'name': n.name, 'status': n.status,
            'fileId': n.drive_file_id,
            'cloudPath': cloud_path,
            'size': n.size,
        })


def run_share_save(
    share_text: str,
    passwd: Optional[str],
    target_dir: Optional[str],
    session_str: str,
) -> int:
    command = 'share-save'
    try:
        result = _do_save(share_text, passwd, target_dir, session_str, command)
    except ShareApiError as e:
        error_meta(command, e.message, code=e.api_code or 'SHARE_API', retryable=not e.fatal)
        return EXIT_BUSINESS_ERROR
    except ShareSaveError as e:
        error_meta(command, str(e), code='USAGE', retryable=False)
        from utils.config import EXIT_INPUT_ERROR

        return EXIT_INPUT_ERROR
    _emit_save_meta(command, result)
    return EXIT_OK if result.pending_count == 0 else EXIT_BUSINESS_ERROR


def run_share_download(
    share_text: str,
    passwd: Optional[str],
    target_dir: Optional[str],
    download_dir: str,
    session_str: str,
) -> int:
    command = 'share-download'
    if not os.path.isdir(download_dir):
        error_meta(command, f'本地目录不存在：{download_dir}', code='USAGE', retryable=False)
        from utils.config import EXIT_INPUT_ERROR

        return EXIT_INPUT_ERROR
    try:
        result = _do_save(share_text, passwd, target_dir, session_str, command)
    except ShareApiError as e:
        error_meta(command, f'转存阶段失败：{e.message}', code=e.api_code or 'SHARE_API',
                   retryable=not e.fatal)
        return EXIT_BUSINESS_ERROR
    except ShareSaveError as e:
        error_meta(command, str(e), code='USAGE', retryable=False)
        from utils.config import EXIT_INPUT_ERROR

        return EXIT_INPUT_ERROR

    _emit_save_meta(command, result, phase='save')
    if result.pending_count and not (result.saved_count + result.existed_count):
        return EXIT_BUSINESS_ERROR

    files = _flatten_files(result.nodes)
    if not files:
        error_meta(command, '转存后没有可下载的文件', code='SHARE_EMPTY', retryable=False)
        return EXIT_BUSINESS_ERROR
    try:
        dl_results, ok_count, fail_count = _download_nodes(files, download_dir)
    except ShareSaveError as e:
        error_meta(command, f'下载阶段失败：{e}', code='SHARE_API', retryable=False)
        return EXIT_BUSINESS_ERROR

    status = 'success' if fail_count == 0 else ('error' if ok_count == 0 else 'warning')
    emit_jsonl({
        'record': 'meta', 'command': command, 'phase': 'download', 'status': status,
        'downloadDir': os.path.abspath(download_dir),
        'okCount': ok_count, 'failCount': fail_count,
    })
    for idx, r in enumerate(dl_results, 1):
        emit_jsonl({'record': 'result', 'index': idx, **r})
    return EXIT_OK if fail_count == 0 else EXIT_BUSINESS_ERROR
