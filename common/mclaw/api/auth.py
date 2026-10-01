#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.api.auth —— 云盘鉴权（单模式：APK 原生业务网关 + 账号会话）。

会话由登录脚本 ``common_auth/mcloud_login.py`` 产出（``--out common_auth/session.json``），
本模块按会话产出业务网关鉴权头：

    Authorization: Basic base64("mobile:" + account + ":" + token)
    x-yun-api-version / x-yun-client-info / x-yun-device-id / x-yun-user-agent /
    x-yun-app-channel / x-yun-net-type / x-yun-svc-type / x-yun-module-type /
    x-yun-uni / x-yun-tid ...

``.env`` 查找顺序：
  1. ``mclaw.api/.env``（同目录，见 ``utils.settings.AuthEnvSettings``）
  2. ``CM_CLOUD_ENV_FILE`` 环境变量指向的文件（最高优先级）
"""

from __future__ import annotations

import base64
import io
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from dotenv import dotenv_values

try:
    from mclaw.api.app_endpoint_map import env_value
except Exception:  # 映射模块缺失时退回纯环境变量
    def env_value(key: str, default: str = '') -> str:
        return (os.getenv(key) or default)

from mclaw.utils.settings import AuthEnvSettings


__all__ = [
    'AuthConfigError',
    'AuthDecryptError',
    'SkillAuthConfig',
    'get_skill_auth',
    'get_auth_header',
    'get_app_common_header',
    'build_native_headers',
    'load_session',
    'session_file_path',
]


# ──────────────────────────── 异常 ────────────────────────────


class AuthConfigError(Exception):
    """鉴权配置异常（会话文件缺失 / 字段不完整等）。"""


class AuthDecryptError(Exception):
    """鉴权信息解密异常（保留类型，新链路不再使用）。"""


# ──────────────────────────── 原生请求头常量 ────────────────────────────

NATIVE_APP_CHANNEL = '10000023'
NATIVE_USER_AGENT = 'android|2203121C|android 13|mCloud13.2.4-032'
NATIVE_HTTP_UA = 'okhttp/4.12.0'
NATIVE_DEVICE_TEMPLATE = (
    '1|127.0.0.1|1|13.2.4|Xiaomi|2203121C|{device_id}|02-00-00-00-00-00|'
    'android 13|1080X2319|zh||||032|0|2274fd15daeabca5|'
)

DEFAULT_CLOUD_HOST = 'https://personal-kd-njs.yun.139.com/hcy'

_PACK_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
)


def _read_env_values() -> Dict[str, str]:
    """读取 ``.env`` 返回 KV 字典，不写入 ``os.environ``。

    查找顺序：``mclaw.api/.env`` → ``CM_CLOUD_ENV_FILE`` 指向的文件（后者覆盖）。
    """
    values: Dict[str, str] = {}

    candidates = [AuthEnvSettings.COMMON_API_ENV_FILE]
    for path in candidates:
        if path and os.path.exists(path):
            for k, v in dotenv_values(path).items():
                if v is not None:
                    values[k] = v

    extra_path = (os.getenv('CM_CLOUD_ENV_FILE') or '').strip()
    if extra_path and os.path.exists(extra_path):
        for k, v in dotenv_values(extra_path).items():
            if v is not None:
                values[k] = v

    return values


def session_file_path() -> str:
    """会话文件路径：``CM_CLOUD_SESSION_FILE``，其次 ``common_auth/session.json``。"""
    packaged = os.path.join(_PACK_ROOT, 'common_auth', 'session.json')
    path = (env_value('CM_CLOUD_SESSION_FILE') or '').strip()
    if path:
        cand = path if os.path.isabs(path) else os.path.join(_PACK_ROOT, path.lstrip('./\\'))
        if os.path.exists(cand):
            return cand
    if os.path.exists(packaged):
        return packaged
    return path


def load_session(path: str = '') -> Dict[str, Any]:
    """读取登录脚本产出的会话文件。"""
    target = path or session_file_path()
    if not target or not os.path.exists(target):
        raise AuthConfigError(
            '未找到登录会话文件：请先运行 common_auth/mcloud_login.py 生成 session.json，'
            '或用 CM_CLOUD_SESSION_FILE 指向该文件。'
        )
    with io.open(target, encoding='utf-8') as fp:
        return json.load(fp)


def _authorization(session: Dict[str, Any]) -> str:
    """Authorization：优先会话里的 authHeader，缺失时按账号+token 现场拼。"""
    auth = str(session.get('authHeader') or '').strip()
    if auth:
        return auth
    account = str(session.get('account') or session.get('userName') or '').strip()
    token = str(session.get('token') or session.get('authToken') or '').strip()
    if not (account and token):
        raise AuthConfigError('会话文件缺少 authHeader，且 account/token 不完整。')
    raw = 'mobile:%s:%s' % (account, token)
    return 'Basic ' + base64.b64encode(raw.encode('utf-8')).decode('ascii')


def build_native_headers(session: Optional[Dict[str, Any]] = None, path: str = '',
                         version: str = '') -> Dict[str, str]:
    """构造 APK 原生业务请求头（任意 IP 可用）。"""
    s = session if isinstance(session, dict) and session else load_session()
    device = NATIVE_DEVICE_TEMPLATE.format(device_id=str(s.get('deviceId') or ''))
    uni = str(s.get('userDomainId') or s.get('userid') or '').strip()
    channel = env_value('CM_CLOUD_APP_CHANNEL') or NATIVE_APP_CHANNEL
    return {
        'x-yun-api-version': version or (env_value('CM_CLOUD_API_VERSION') or 'v1'),
        'Connection': 'keep-alive',
        'x-yun-net-type': '1',
        'x-yun-client-info': device,
        'x-yun-svc-type': '1',
        'x-yun-module-type': '100',
        'x-yun-device-id': device,
        'x-yun-user-agent': NATIVE_USER_AGENT,
        'x-yun-app-channel': channel,
        'Accept-Language': 'zh-CN',
        'x-yun-tid': str(uuid.uuid4()),
        'x-yun-uni': uni,
        'Authorization': _authorization(s),
        'Content-Type': 'application/json; charset=UTF-8',
        'User-Agent': NATIVE_HTTP_UA,
    }


# ──────────────────────────── 配置 dataclass ────────────────────────────


@dataclass
class SkillAuthConfig:
    """会话视图：所有运行期凭据都来自 ``session.json``。

    ``get_skill_auth()`` 在每次调用时按 ``.env`` 构造新实例；凭据字段按需读会话文件。
    """

    host: str = ''
    app_name: str = ''
    app_id: str = ''
    session_path: str = ''
    _session: Optional[Dict[str, Any]] = field(default=None, repr=False, compare=False)

    def get_session(self) -> Dict[str, Any]:
        if self._session is None:
            self._session = load_session(self.session_path)
        return self._session

    # ── 字段访问（保持历史调用点兼容）────────────────────────
    def get_access_token(self) -> str:
        return str(self.get_session().get('token') or '')

    def get_app_key(self) -> str:
        """群组/外链等旧 Open API 用 appKey；账号会话模式下无该字段。"""
        return str(self.get_session().get('appKey') or '')

    def get_secret_key(self) -> str:
        return str(self.get_session().get('secinfo') or '')

    def get_or_create_device_id(self) -> str:
        return str(self.get_session().get('deviceId') or '')

    def get_channel_id(self) -> str:
        return ''

    def get_upload_dir(self) -> str:
        return ''

    # ── 鉴权头 ─────────────────────────────────────────────
    def get_common_header(self, path: str = '') -> dict:
        """业务网关通用鉴权头（Authorization: Basic + 全套 x-yun-*）。"""
        return build_native_headers(self.get_session(), path=path)


def _build_skill_auth_config() -> SkillAuthConfig:
    values = _read_env_values()
    return SkillAuthConfig(
        host=values.get('CM_CLOUD_HOST') or DEFAULT_CLOUD_HOST,
        app_name=values.get('CM_CLOUD_APP_NAME') or '',
        app_id=values.get('CM_CLOUD_APP_ID') or '',
        session_path=session_file_path(),
    )


def get_skill_auth() -> SkillAuthConfig:
    """返回云盘 CLI 共享鉴权配置；每次调用都重新读取 ``.env`` 构造新实例。"""
    return _build_skill_auth_config()


def get_app_common_header(path: str = '') -> dict:
    """当前会话的原生业务鉴权头（缺失登录态时抛 AuthConfigError）。"""
    return get_skill_auth().get_common_header(path=path)


def get_auth_header() -> dict:
    """标准云盘 JSON/XML 接口鉴权头。"""
    return get_skill_auth().get_common_header()