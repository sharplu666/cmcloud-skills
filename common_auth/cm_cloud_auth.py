#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云盘 skills 鉴权（单模式：APK 原生业务网关 + 账号会话）。

会话由登录脚本 ``common_auth/mcloud_login.py`` 产出::

    python mcloud_login.py --account <手机号> --password <密码> --out common_auth/session.json

``session.json`` 内含 ``account`` / ``userDomainId`` / ``deviceId`` / ``token`` /
``authHeader``；本模块只做两件事：

1. 读 ``.env``（``CM_CLOUD_SESSION_FILE`` / ``CM_CLOUD_APP_NAME`` / ``CM_CLOUD_HOST``）；
2. 为每个业务网关请求产出鉴权头：
   ``Authorization: Basic base64("mobile:" + account + ":" + token)`` + 全套 ``x-yun-*``。

任意出口 IP 可用；凭据缺失时抛 ``AuthConfigError``，提示重新跑登录脚本。
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

X_YUN_CLIENT_INFO = '||36|2.7.7||Nexus 5|10ff6362-b90c-4dc0-86bb-6b95d130cc4a||android 6.0|||||'

GROUP_CIRCLE_DEFAULT_X_DEVICE_INFO = (
    '||36|3.0.0||iPhone|8e1fe11a-8922-44ef-8838-4ba3791e9723||ios 13.2.3|||||'
)

# 是否在 CLI stdout 首行输出 record=timing；仅在此修改，不读 .env。
CM_CLOUD_DEBUG_ENABLED: bool = False

# 业务默认 HOST（仅用于未登记映射的路径；已登记路径由 app_endpoint_map 改写）
DEFAULT_CLOUD_HOST = 'https://personal-kd-njs.yun.139.com/hcy'

NATIVE_APP_CHANNEL = '10000023'
NATIVE_USER_AGENT = 'android|2203121C|android 13|mCloud13.2.4-032'
NATIVE_HTTP_UA = 'okhttp/4.12.0'
NATIVE_DEVICE_TEMPLATE = (
    '1|127.0.0.1|1|13.2.4|Xiaomi|2203121C|{device_id}|02-00-00-00-00-00|'
    'android 13|1080X2319|zh||||032|0|2274fd15daeabca5|'
)


class AuthConfigError(Exception):
    """鉴权配置异常（会话文件缺失 / 字段不完整等）。"""


class AuthDecryptError(Exception):
    """鉴权信息解密异常（保留类型，新链路不再使用）。"""


def normalize_cm_cloud_host(url: str) -> str:
    """规范化知识库/开放平台类配置里的 HOST（去重复路径段、去掉知识库后缀等）。"""
    h = (url or '').strip().rstrip('/')
    if not h:
        return ''
    while '/open-api/open-api' in h:
        h = h.replace('/open-api/open-api', '/open-api', 1)
    if h.endswith('/richlifeApp/knowledgeBase'):
        h = h[: -len('/richlifeApp/knowledgeBase')].rstrip('/')
    return h.rstrip('/')


_COMMON_AUTH_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_FILE = os.path.join(_COMMON_AUTH_DIR, '.env')
_CM_ENV_CANDIDATES = [
    _ENV_FILE,
    os.path.join(os.path.dirname(_COMMON_AUTH_DIR), 'common', 'mclaw', 'api', '.env'),
]


def env_value(key: str, default: str = '') -> str:
    """读配置：``os.environ`` 优先，缺失时回落到打包内的 ``.env``。"""
    value = (os.getenv(key) or '').strip()
    if value:
        return value
    paths = [p for p in _CM_ENV_CANDIDATES if p and os.path.exists(p)]
    extra = (os.getenv('CM_CLOUD_ENV_FILE') or '').strip()
    if extra:
        paths.append(extra)
    for path in paths:
        try:
            got = dotenv_values(path).get(key)
        except Exception:
            got = None
        if got:
            return str(got).strip()
    return default


def _read_env_values() -> Dict[str, str]:
    """直接读取 ``.env`` 返回 KV 字典，不写入 ``os.environ``。"""
    values: Dict[str, str] = {}
    if os.path.exists(_ENV_FILE):
        for k, v in dotenv_values(_ENV_FILE).items():
            if v is not None:
                values[k] = v
    extra_path = (os.getenv('CM_CLOUD_ENV_FILE') or '').strip()
    if extra_path and os.path.exists(extra_path):
        for k, v in dotenv_values(extra_path).items():
            if v is not None:
                values[k] = v
    return values


def session_file_path() -> str:
    """会话文件路径：``CM_CLOUD_SESSION_FILE``，其次包内 ``common_auth/session.json``。

    相对路径按包根目录解析，便于整包搬迁后免改配置。
    """
    pack_root = os.path.dirname(_COMMON_AUTH_DIR)
    packaged = os.path.join(_COMMON_AUTH_DIR, 'session.json')
    path = (env_value('CM_CLOUD_SESSION_FILE') or '').strip()
    if path:
        cand = path if os.path.isabs(path) else os.path.join(pack_root, path.lstrip('./\\'))
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
    """Authorization 头：优先用会话里的 authHeader，缺失时按账号+token 现场拼。"""
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


@dataclass
class SkillAuthConfig:
    """会话视图：所有运行期凭据都来自 ``session.json``。

    ``host`` / ``app_name`` / ``app_id`` 为部署配置（``.env``），不是凭据。
    ``get_*`` 系列每次读取会话文件，禁止跨请求复用实例做进程内缓存。
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

    def get_common_header(self, path: str = '') -> dict:
        """业务网关通用鉴权头（Authorization: Basic + 全套 x-yun-*）。"""
        return build_native_headers(self.get_session(), path=path)

    def get_album_header(self) -> dict:
        h = dict(self.get_common_header())
        h['Content-Type'] = 'application/json'
        h['x-yun-client-info'] = X_YUN_CLIENT_INFO
        return h

    def get_album_share_header(self) -> dict:
        h = self.get_album_header()
        h['x-DeviceInfo'] = X_YUN_CLIENT_INFO
        return h


def _build_skill_auth_config() -> SkillAuthConfig:
    values = _read_env_values()
    return SkillAuthConfig(
        host=values.get('CM_CLOUD_HOST') or DEFAULT_CLOUD_HOST,
        app_name=values.get('CM_CLOUD_APP_NAME') or '',
        app_id=values.get('CM_CLOUD_APP_ID') or '',
        session_path=session_file_path(),
    )


def get_skill_auth() -> SkillAuthConfig:
    """返回云盘 CLI 共享鉴权配置；每次调用都直接读取 ``.env`` 并构建新实例。"""
    return _build_skill_auth_config()


def get_app_common_header(path: str = '') -> dict:
    """当前会话的原生业务鉴权头（缺失登录态时抛 AuthConfigError）。"""
    return get_skill_auth().get_common_header(path=path)


def get_auth_header() -> dict:
    """标准云盘 JSON/XML 接口鉴权头。"""
    return get_skill_auth().get_common_header()


def group_circle_x_device_info() -> str:
    custom = os.getenv('CM_CLOUD_X_DEVICE_INFO', '').strip()
    return custom if custom else GROUP_CIRCLE_DEFAULT_X_DEVICE_INFO


def group_circle_open_api_headers(app_id: str) -> dict:
    """群组 Open API 鉴权头：原生通用头 + ``x-DeviceInfo``。"""
    h = get_auth_header()
    h['x-DeviceInfo'] = group_circle_x_device_info().strip()
    return h


def group_circle_publish_device_id() -> str:
    """发布动态等接口 body 中的 deviceId（取自会话）。"""
    return get_skill_auth().get_or_create_device_id()


class KbManageSetting:
    """知识库 Open API 运行时配置（HOST 规范化、HTTP 超时）。"""

    def __init__(self) -> None:
        self.timeout = int(os.getenv('CM_KB_TIMEOUT', '10'))

    @property
    def host(self) -> str:
        raw = get_skill_auth().host
        out = normalize_cm_cloud_host(raw)
        if out:
            return out
        raise AuthConfigError('未配置 CM_CLOUD_HOST，无法调用知识库接口。')


kb_manage_setting = KbManageSetting()


def get_kb_auth_header() -> dict:
    """知识库 Open API：云盘通用鉴权头 + ``x-yun-client-info``。"""
    h = get_auth_header()
    h['x-yun-client-info'] = X_YUN_CLIENT_INFO
    return h


def is_cm_cloud_debug() -> bool:
    """是否输出 record=timing（见 ``CM_CLOUD_DEBUG_ENABLED``）。"""
    return CM_CLOUD_DEBUG_ENABLED


__all__ = [
    'AuthConfigError', 'AuthDecryptError', 'SkillAuthConfig',
    'get_auth_header', 'get_app_common_header', 'get_skill_auth',
    'get_kb_auth_header', 'group_circle_open_api_headers',
    'group_circle_publish_device_id', 'group_circle_x_device_info',
    'normalize_cm_cloud_host', 'env_value', 'is_cm_cloud_debug',
    'load_session', 'session_file_path', 'build_native_headers',
    'kb_manage_setting', 'KbManageSetting',
    'X_YUN_CLIENT_INFO', 'GROUP_CIRCLE_DEFAULT_X_DEVICE_INFO',
]