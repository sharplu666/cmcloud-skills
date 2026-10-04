#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分享链接输入解析：从用户粘贴的整段分享文本中抠出 (link_id, passwd)。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ShareRef:
    link_id: str
    passwd: str = ''


def parse_share_input(text: str) -> ShareRef:
    """解析分享链接文本，返回 ShareRef。

    支持：
    - 链接形如 https://yun.139.com/shareweb/#/w/i/<id>（取 id；也兼容纯 id 输入）
    - 提取码在 URL 参数 ?pwd=xxx / ?code=xxx / ?passwd=xxx
    - 提取码在文本中"提取码:xxxx" / "访问码:xxxx" / "密码:xxxx" / "pwd:xxxx"
    - 都没有时 passwd 为空，交由接口判断是否需要密码
    """
    text = (text or '').strip()
    link_id = ''
    pwd = ''

    # 1) 链接 ID：shareweb 路径里的 /w/i/<id>，或退化为 /i/<id>
    m = re.search(r'/w/i/([A-Za-z0-9_-]+)', text)
    if not m:
        m = re.search(r'/i/([A-Za-z0-9_-]+)', text)
    if m:
        link_id = m.group(1)
    elif re.fullmatch(r'[A-Za-z0-9_-]{6,64}', text):
        # 纯分享 ID 直接输入
        link_id = text

    # 2) 提取码优先从 URL 参数取
    um = re.search(r'[?&](?:pwd|code|passwd)=([A-Za-z0-9]+)', text, re.I)
    if um:
        pwd = um.group(1)
    else:
        pm = re.search(
            r'(?:提取码|访问码|密码|pwd|code)\s*[:：]?\s*([A-Za-z0-9]{3,16})',
            text,
            re.I,
        )
        if pm:
            pwd = pm.group(1)

    return ShareRef(link_id=link_id, passwd=pwd)


def resolve_passwd(explicit: Optional[str], parsed: ShareRef) -> str:
    """--passwd 显式参数优先，否则用文本里解析出的提取码。"""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    return parsed.passwd
