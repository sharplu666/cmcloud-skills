#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云盘取图 / 上传（edit 业务编排用；dispatcher 注入，便于离线测试替换）。"""

import os
from datetime import datetime, timezone
from typing import Tuple

import requests

from mclaw.api import ApiDispatcher
from mclaw.api.personal_saas.batch_get_api import BatchGetRequest
from mclaw.api.personal_saas.batch_get_download_url_api import BatchGetDownloadUrlRequest
from mclaw.api.personal_saas.file_create_api import FileCreateRequest
from mclaw.api.personal_saas.file_complete_api import FileCompleteRequest

from utils.tools import _DOWNLOAD_TIMEOUT, _UPLOAD_TIMEOUT, sha256_file


def _fetch_cloud_file_meta(dispatcher: ApiDispatcher, file_id: str) -> str:
    """batch_get 校验 fileId 存在性并取文件名；不存在则抛错。"""
    resp = dispatcher.personal_saas.batch_get(BatchGetRequest(file_ids=[file_id]))
    raw_results = (((resp.raw or {}).get('data') or {}).get('batchFileResults') or [])
    for row in raw_results:
        if not isinstance(row, dict):
            continue
        src = row.get('srcFile') or {}
        fid = str(src.get('fileId') or row.get('fileId') or '').strip()
        if fid == file_id and src:
            return str(src.get('name') or '').strip()
    raise RuntimeError(f"输入图片 fileId 不存在或无法访问: {file_id}")


def download_cloud_file(dispatcher: ApiDispatcher, file_id: str, download_dir: str) -> Tuple[str, str]:
    """下载云盘图片到本地目录，返回 (本地路径, 云盘文件名)。"""
    name = _fetch_cloud_file_meta(dispatcher, file_id)
    url_resp = dispatcher.personal_saas.batch_get_download_url(
        BatchGetDownloadUrlRequest(file_ids=[file_id])
    )
    url = ''
    for item in url_resp.items:
        if item.file_id == file_id and str(item.err_code or '0000') == '0000':
            url = item.url
            break
    if not url:
        raise RuntimeError(f"获取下载地址失败: {file_id}")
    os.makedirs(download_dir, exist_ok=True)
    local_path = os.path.join(download_dir, name or f"{file_id}.png")
    resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"下载图片失败: HTTP {resp.status_code}")
    with open(local_path, 'wb') as f:
        f.write(resp.content)
    # 轻量校验：下载不完整时告警（截断容错兜底解码），不中断流程
    expected = resp.headers.get('Content-Length')
    if expected and expected.isdigit():
        actual = os.path.getsize(local_path)
        if actual != int(expected):
            print(f"警告: 下载字节数不完整（{actual}/{expected}），将尝试容错解码: {name or file_id}")
    return local_path, name


def upload_local_file(
    dispatcher: ApiDispatcher,
    local_path: str,
    parent_file_id: str,
    verbose: bool = False,
) -> Tuple[str, str]:
    """上传本地文件到指定云盘目录（create → PUT → complete），返回 (fileId, 最终文件名)。"""
    name = os.path.basename(local_path)
    size = os.path.getsize(local_path)
    create = dispatcher.personal_saas.file_create(
        FileCreateRequest(name=name, size=size, parent_file_id=parent_file_id)
    )
    if not create.file_id:
        raise RuntimeError(f"创建远端文件记录失败: {create.raw}")
    if create.rapid_upload:
        if verbose:
            print(f"秒传命中，跳过 PUT: fileId={create.file_id}")
        return create.file_id, create.file_name or name
    put_url = create.first_part_upload_url
    if not put_url:
        raise RuntimeError("未取得上传地址（partInfos 为空）")
    headers = {
        'Host': put_url.split('/')[2],
        'Date': datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT'),
        'Content-Type': 'application/octet-stream',
    }
    with open(local_path, 'rb') as f:
        resp = requests.put(put_url, data=f, headers=headers, timeout=_UPLOAD_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"上传文件失败: HTTP {resp.status_code} {resp.text}")
    dispatcher.personal_saas.file_complete(
        FileCompleteRequest(
            upload_id=create.upload_id,
            file_id=create.file_id,
            content_hash=sha256_file(local_path),
        )
    )
    return create.file_id, create.file_name or name
