#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""139 分享 V6 接口客户端（share-kd-njs.yun.139.com）。

协议：明文 JSON POST，无需 mcloud-sign 签名、无需请求体加密。
转存接口需要登录态：Authorization: Basic base64("mobile:<account>:<token>")，
与 skill 自身业务网关鉴权方式一致，凭据取自 common_auth/session.json。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

SHARE_HOST = 'https://share-kd-njs.yun.139.com'
_GET_INFO_PATH = '/yun-share/richlifeApp/devapp/IOutLink/getOutLinkInfoV6'
_SAVE_PATH = '/yun-share/richlifeApp/devapp/IBatchOprTask/createOuterLinkBatchOprTask'

SHARE_HEADERS = {
    'caller': 'web',
    'x-m4c-caller': 'PC',
    'mcloud-client': '10701',
    'mcloud-version': '7.17.2',
    'mcloud-channel': '1000101',
    'Content-Type': 'application/json',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    ),
}

# 致命错误码：无需重试（链接失效/过期/次数超限等）
FATAL_CODES = {
    '200000727': '分享链接不存在或已被分享者取消',
    '200000401': '分享链接已过期',
    '200000402': '分享链接已达访问次数上限',
    '05010003': '查询不到用户信息',
    '04000005': '认证失败',
    '05050006': 'token 失效，请重新登录',
}

TIMEOUT = 60


class ShareApiError(Exception):
    """分享接口错误。fatal=True 表示无需重试。"""

    def __init__(self, message: str, code: Optional[str] = None, fatal: bool = False):
        super().__init__(message)
        self.message = message
        self.api_code = code
        self.fatal = fatal


@dataclass
class ShareItem:
    """分享内的一个文件或文件夹节点。"""
    kind: str  # 'file' | 'folder'
    name: str
    share_id: str
    share_path: str  # 转存用 path（parentID/ID 格式）
    size: int = 0
    children: List['ShareItem'] = field(default_factory=list)


def _load_account_token() -> tuple[str, str]:
    from cm_cloud_auth import load_session

    sess = load_session()
    account = str(sess.get('account') or sess.get('userName') or '').strip()
    token = str(sess.get('token') or sess.get('authToken') or '').strip()
    if not (account and token):
        raise ShareApiError('登录会话缺少 account/token，请先登录移动云盘账号', fatal=True)
    return account, token


def get_session_account() -> str:
    """当前登录账号（手机号）。"""
    account, _ = _load_account_token()
    return account


def _authorization() -> tuple[str, str]:
    account, token = _load_account_token()
    raw = 'mobile:%s:%s' % (account, token)
    return account, 'Basic ' + base64.b64encode(raw.encode('utf-8')).decode('ascii')


def _post(path: str, body: Dict[str, Any], with_auth: bool = False) -> Dict[str, Any]:
    headers = dict(SHARE_HEADERS)
    if with_auth:
        _, headers['Authorization'] = _authorization()
    try:
        r = requests.post(SHARE_HOST + path, headers=headers, json=body, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ShareApiError(f'请求 139 分享接口失败: {e}')
    try:
        resp = r.json()
    except Exception:
        raise ShareApiError(f'139 分享接口返回非 JSON（HTTP {r.status_code}）')
    code = resp.get('code')
    if code not in (0, '0', None):
        desc = str(resp.get('desc') or resp.get('message') or '未知错误')
        c = str(code)
        hint = FATAL_CODES.get(c, '')
        msg = f'139 分享接口错误 [{c}]: {desc}'
        if hint:
            msg += f'（{hint}）'
        elif 'passwd' in desc.lower() or '密码' in desc or '提取码' in desc:
            msg += '（若分享设有提取码，请用 --passwd 传入）'
        raise ShareApiError(msg, code=c, fatal=(c in FATAL_CODES))
    data = resp.get('data', resp)
    return data if isinstance(data, dict) else {}


def get_share_info(
    link_id: str,
    passwd: str = '',
    p_ca_id: str = 'root',
    start: int = 1,
    end: int = 200,
) -> Dict[str, Any]:
    """查询分享信息/文件列表（单页）。"""
    body = {
        'getOutLinkInfoReq': {
            'account': '',
            'linkID': link_id,
            'passwd': passwd or '',
            'pCaID': p_ca_id,
            'caSrt': 0,
            'coSrt': 0,
            'srtDr': 1,
            'bNum': start,
            'eNum': end,
        },
    }
    return _post(_GET_INFO_PATH, body)


def list_share_tree(link_id: str, passwd: str = '') -> tuple[List[ShareItem], Dict[str, Any]]:
    """递归列出分享内全部文件/文件夹，返回 (顶层节点列表, 分享元信息)。"""
    meta: Dict[str, Any] = {}

    def _fetch(dir_id: str, start: int = 1) -> List[ShareItem]:
        nonlocal meta
        info = get_share_info(link_id, passwd, dir_id, start, start + 199)
        if not meta and dir_id == 'root':
            meta = {
                'shareName': info.get('lkName') or '',
                'creator': info.get('creator') or '',
                'expireTime': info.get('expireTime') or '',
            }
        nodes: List[ShareItem] = []
        for f in info.get('coLst') or []:
            cid = str(f.get('contentID') or f.get('coID') or '')
            if not cid:
                continue
            nodes.append(ShareItem(
                kind='file',
                name=str(f.get('contentName') or f.get('coName') or cid),
                share_id=cid,
                share_path=str(f.get('path') or f'{dir_id}/{cid}'),
                size=int(f.get('contentSize') or f.get('coSize') or 0),
            ))
        for d in info.get('caLst') or []:
            cid = str(d.get('catalogID') or d.get('caID') or '')
            if not cid:
                continue
            children = _fetch(cid)
            nodes.append(ShareItem(
                kind='folder',
                name=str(d.get('catalogName') or d.get('caName') or d.get('name') or cid),
                share_id=cid,
                share_path=str(d.get('path') or f'{dir_id}/{cid}'),
                children=children,
            ))
        total = int(info.get('nodNum') or 0)
        if start + 199 < total:
            nodes.extend(_fetch(dir_id, start + 200))
        return nodes

    return _fetch('root'), meta


def save_share(
    link_id: str,
    passwd: str,
    file_paths: List[str],
    folder_paths: List[str],
    target_catalog_id: str,
) -> str:
    """提交转存任务，把分享文件/文件夹保存到自己云盘目标目录。返回 taskID。"""
    account, _ = _load_account_token()
    need_pwd = bool(passwd)
    body = {
        'createOuterLinkBatchOprTaskReq': {
            'msisdn': account,
            'ownerAccount': '',
            'taskType': 1,
            'linkID': link_id,
            'needPassword': need_pwd,
            'taskInfo': {
                'linkID': link_id,
                'needPassword': need_pwd,
                'contentInfoList': list(file_paths),
                'catalogInfoList': list(folder_paths),
                'newCatalogID': target_catalog_id,
            },
        },
    }
    data = _post(_SAVE_PATH, body, with_auth=True)
    task_id = str(data.get('taskID') or data.get('taskId') or '').strip()
    if not task_id:
        raise ShareApiError(f'转存任务提交未返回 taskID：{data}')
    return task_id
