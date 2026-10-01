#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用辅助：鉴权、解析、路径、重命名。"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

class CloudManageError(RuntimeError):
    """Shared business error for 中国移动「云盘文件管理」 scripts."""

def atomic_write_text(path: Path, text: str) -> None:
    """同目录临时文件 + ``os.replace`` 原子替换（半截文件不被下游当全量消费）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def sha256_file(path: str, chunk_size: int = 8192) -> str:
    """计算本地文件的 SHA256 哈希值。"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()

def normalize_ext(ext: str) -> str:
    return str(ext or '').strip().lstrip('.').lower()

def extract_name_ext(name: str) -> str:
    text = str(name or '').strip()
    if '.' not in text:
        return ''
    _, _, ext = text.rpartition('.')
    return normalize_ext(ext)

def normalize_rename_target_name(file_info: dict[str, Any], target_name: str) -> tuple[str, bool]:
    normalized_name = str(target_name or '').strip()
    original_name = str(file_info.get('fileName') or '')
    original_ext = normalize_ext(str(file_info.get('fileExtension') or '')) or extract_name_ext(original_name)
    if not original_ext:
        return normalized_name, False

    target_ext = extract_name_ext(normalized_name)
    if target_ext == original_ext:
        return normalized_name, False

    match = re.search(
        rf'(?i)\.({re.escape(original_ext)})(?![a-zA-Z0-9])',
        normalized_name,
    )
    if match and match.start() > 0:
        before = normalized_name[:match.start()]
        after = normalized_name[match.end():]
        final_base = f'{before}{after}'.strip()
        if not final_base:
            return f'{normalized_name}.{original_ext}', True
        if final_base.endswith('.'):
            final_base = final_base[:-1]
        return f'{final_base}.{original_ext}', True

    base_name = normalized_name[: -(len(target_ext) + 1)] if target_ext else normalized_name
    base_name = base_name.rstrip() or original_name
    return f'{base_name}.{original_ext}', True
