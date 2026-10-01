#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""richlifeApp(Open API) -> APK 原生接口 的端点映射表。

用法：``mclaw.api.base._BaseApi._resolve_url`` 会把每个叶子接口的 PATH
改写到 APK 里功能等价的接口（含 host 切换）。

证据来源：ydyp\\decomp*\\sources 里各 *RetrofitFactory.java 的 BASE_URL
与本表 path 所属的 retrofit interface（见 APK-ENDPOINTS.md）。

注意：本表只替换 **host + path**。请求体/响应体schema不同的接口，
另见 APP-ENDPOINT-MAP.md 的“payload/加密”列。
"""

from __future__ import annotations

import base64
import io
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# APK 各模块 BASE_URL（取自对应 *RetrofitFactory 的 BASE_URL / create()）
# ---------------------------------------------------------------------------
HOSTS: Dict[str, str] = {
    'ai':        'https://ai.yun.139.com',                   # AIRetrofitFactory / PhotoToolAIYunRetrofitFactory / AlgorithmCenter*
    'phototool': 'https://ai.yun.139.com/aitools/applet',    # PhotoToolRetrofitFactory
    'personal':  'https://personal-kd-njs.yun.139.com/hcy',  # PersonSaasRetrofitFactory (router: personal)
    'album':     'https://album-njs.yun.139.com/album',      # AlbumSaasRetrofitFactory
    'user':      'https://user-njs.yun.139.com',             # UserDomainRetrofitFactory
    'share':     'https://share-kd-njs.yun.139.com/yun-share',  # ShareRetrofitFactory / MemoryAlbum
    'search':    'https://search-njs.yun.139.com/search',    # PdsRetrofitFactory / SpaceSearch
    'bookshelf': 'https://bookshelf-njs.yun.139.com/bookshelf',  # BookshelfRetrofitFactory
    'note':      'https://note-njs.yun.139.com',             # note SDK ApiConfiguration
    'group':     'https://group.yun.139.com/hcy/group',      # CircleRetrofitFactory
    'family':    'https://group.yun.139.com/hcy/family/adapter',  # PsboRetrofitFactory
    'mutual':    'https://group.yun.139.com/hcy/mutual/adapter',  # IsboRetrofitFactory
    'dynamic':   'https://huidu-middle.yun.139.com/openapi', # DynamicRetrofitFactory / Caixun
    'avatar':    'https://middle.yun.139.com/yun-user-avatar',  # UserAvatarRetrofitFactory
    'auth':      'https://yun.139.com/caiyun',              # AuthenticationRetrofitFactory (IAuthenticationApi)
}

# ---------------------------------------------------------------------------
# Open API path -> (host_key, APK path)
# ---------------------------------------------------------------------------
ENDPOINT_MAP: Dict[str, Tuple[str, str]] = {
    # ── 文件 / 个人云（IPersonSaasApi @ personal-kd-njs/hcy） ──────────────
    '/richlifeApp/personalSaas/file/batchCheckExists':    ('personal', 'file/batchCheckExists'),
    '/richlifeApp/personalSaas/file/batchGet':            ('personal', 'file/batchGet'),
    '/richlifeApp/personalSaas/file/batchUpdate':         ('personal', 'file/batchUpdate'),
    '/richlifeApp/personalSaas/file/create':              ('personal', 'file/create'),
    '/richlifeApp/personalSaas/file/complete':            ('personal', 'file/complete'),
    '/richlifeApp/personalSaas/file/createFolder':        ('personal', 'file/create'),            # type=folder
    '/richlifeApp/personalSaas/file/batchMoveAsync':      ('personal', 'file/batchMove'),        # APK 为同步 batchMove
    '/richlifeApp/personalSaas/file/batchGetPath':        ('personal', 'file/getPath'),
    '/richlifeApp/personalSaas/file/batchGetDownloadUrl': ('personal', 'file/getDownloadUrl'),   # APK 单文件版
    '/richlifeApp/personalSaas/task/get':                 ('personal', 'task/get'),
    '/richlifeApp/personalSaas/videoPreview/getPreviewInfo': ('personal', 'videoPreview/getPreviewInfo'),
    # 无对应：/richlifeApp/personalSaas/file/batchCopy（APK 无 file/batchCopy）

    # ── 相册 / 分类（IAlbumSaasApi @ album-njs/album） ─────────────────────
    '/richlifeApp/personalSaas/album/classify/addr/list':            ('album', 'classify/addr/list'),
    '/richlifeApp/personalSaas/album/classify/addr/file/list':       ('album', 'classify/addr/file/list'),
    '/richlifeApp/personalSaas/album/classify/person/list':          ('album', 'classify/person/list'),
    '/richlifeApp/personalSaas/album/classify/person/file/list':     ('album', 'classify/person/file/list'),
    '/richlifeApp/personalSaas/album/classify/thing/list':           ('album', 'classify/thing/list'),
    '/richlifeApp/personalSaas/album/classify/thing/file/list':      ('album', 'classify/thing/file/list'),
    '/richlifeApp/personalSaas/album/photo/customization/list':      ('album', 'photo/customization/list'),
    '/richlifeApp/personalSaas/album/photo/customization/add':       ('album', 'photo/customization/add'),
    '/richlifeApp/personalSaas/album/photo/customization/update':    ('album', 'photo/customization/update'),
    '/richlifeApp/personalSaas/album/photo/customization/file/list': ('album', 'photo/customization/file/list'),
    '/richlifeApp/personalSaas/album/photo/customization/file/add':  ('album', 'photo/customization/file/add'),
    '/richlifeApp/personalSaas/album/story/memory/list':             ('album', 'story/memory/list'),
    '/richlifeApp/personalSaas/album/story/memory/add':              ('album', 'story/memory/add'),
    '/richlifeApp/personalSaas/album/story/memory/update':           ('album', 'story/memory/update'),
    '/richlifeApp/personalSaas/album/story/memory/file/list':        ('album', 'story/memory/file/list'),
    '/richlifeApp/personalSaas/album/story/memory/playlist/add':     ('album', 'story/memory/playlist/add'),
    '/richlifeApp/personalSaas/album/share/getAlbumShareInfo':       ('share', 'share/api/getAlbumShareInfo.do'),
    '/richlifeApp/search/SearchAIStory':                             ('album', 'story/recommend/memory/list'),

    # ── 图片工具 / AI（PhotoToolAIYun / IAIApi @ ai.yun.139.com） ──────────
    '/richlifeApp/aiService/api/image/generate':        ('ai', 'api/image/generate'),
    '/richlifeApp/aiService/api/image/edit/shift':      ('ai', 'api/image/edit/shift'),
    '/richlifeApp/aiService/api/image/edit/locate':     ('ai', 'api/image/edit/locate'),
    '/richlifeApp/aiService/api/image/quality/repair':  ('ai', 'api/image/edit/enhance'),
    '/richlifeApp/aiService/api/image/detect/face':     ('ai', 'api/image/faceInfo/get'),
    '/richlifeApp/aiService/api/async/task/result':     ('ai', 'api/outer/async/task/result'),
    '/richlifeApp/aiService/api/text/intelligent/search/merge/file':   ('ai', 'intelligent/search/merge/file'),
    '/richlifeApp/aiService/api/text/intelligent/search/merge/image':  ('ai', 'intelligent/search/merge/image'),
    '/richlifeApp/aiService/api/text/intelligent/search/note':         ('ai', 'intelligent/search/note'),
    '/richlifeApp/aiService/api/text/intelligent/search/merge/image/aiAnalysisInfo': ('ai', 'api/image/cardinfo/analysis'),
    '/richlifeApp/api/text/intelligent/search/face/recognize':         ('ai', 'intelligent/search/image'),
    '/richlifeApp/api/videosec/videocreation/task/create':   ('ai', 'api/videosec/videocreation/task/create'),
    '/richlifeApp/api/videosec/videocreation/task/estimate': ('ai', 'api/videosec/videocreation/task/estimate'),
    '/richlifeApp/api/videosec/videocreation/task/query':    ('ai', 'api/videosec/videocreation/task/query'),
    # 无对应（APK 未提取到同名算法）：alivePhoto / avatar/cartoon / beautify/face / caption /
    #   deduplicate / edit/babyTimeMachine / edit/faceAnime / edit/gabyGrowthPrediction /
    #   edit/imageCutout / expand / restore/oldPhoto / textToImage

    # ── 分享 / 外链（IShareApi @ share-kd-njs/yun-share） ─────────────────
    '/richlifeApp/devapp/share/subOutLink':                    ('share', 'subscribe/outLink/subOutLink'),
    '/richlifeApp/devapp/share/createOuterLinkBatchOprTask':   ('share', 'subscribe/outLink/createOuterLinkBatchOprTask'),
    '/richlifeApp/devapp/createOuterLinkBatchOprTaskV2':       ('share', 'hcy/group/outlink/createOuterLinkBatchOprTask'),
    '/richlifeApp/devapp/share/createSpecShareLink':           ('share', 'common/api/aicontact/createSpecShareLink'),
    '/richlifeApp/devapp/share/getUpdateAssets':               ('share', 'subscribe/outLink/getUpdateOutContentList'),
    '/richlifeApp/devapp/getOutLinkNew':                       ('share', 'general/IOutLink/getOutLinkList'),
    '/richlifeApp/devapp/getOutLinkInfo':                      ('share', 'general/IOutLink/queryOutLinkShareChannel'),
    '/richlifeApp/search/SearchShareRecord':                   ('share', 'subscribe/outLink/getShareOutLinkList'),
    '/richlifeApp/search/SearchSubscribeShareCode':            ('share', 'subscribe/outLink/checkShared'),

    # ── 群组 / 圈子（ICircleApi @ group.yun.139.com/hcy/group） ───────────
    '/richlifeApp/devapp/hcy/group/manage/myCreateGroupList':  ('group', 'manage/circle/myCreateGroupList'),
    '/richlifeApp/devapp/hcy/group/manage/myJoinList':         ('group', 'manage/circle/myJoinList'),
    '/richlifeApp/devapp/manage/search/searchGroup/v5':        ('group', 'manage/search/searchGroup'),
    '/richlifeApp/devapp/hcy/group/dynamic/assets/queryMultiTaskStatus': ('group', 'dynamic/assets/queryMultiTaskStatus'),
    '/richlifeApp/devapp/circle/publishCircle':                ('group', 'dynamic/circle/publishCloudDynamic'),

    # ── 书架 / 阅读记录（IBookshelfAPI @ bookshelf-njs/bookshelf） ────────
    '/richlifeApp/bookshelf/readingRecord/list': ('bookshelf', 'readingRecord/list'),

    # ── 第二轮 dex 挖掘补齐（note SDK / authentication / dynamic） ─────────
    # note SDK：@POST(NOTE_API_*) 常量，定义在 NoteRefactorApiService.java，基址 NOTE_API_REFACTOR_URL
    '/richlifeApp/note/getNoteDetail':        ('note', 'yun-note/note/getNoteDetail'),        # NOTE_API_INFO_DETAIL
    '/richlifeApp/note/createAgentNote':      ('note', 'yun-note/note/createNote'),            # APK 无 createAgentNote，取笔记创建
    '/richlifeApp/attachment/fileSaveToNote': ('note', 'yun-note/note/fileSaveToNote'),        # NOTE_API_FILE_SAVE_TO_NOTE
    '/richlifeApp/notebook/createNotebook':   ('note', 'yun-note/notebook/syncNotebookV3'),    # APK 无 createNotebook，notebook 走同步协议
    # 知识库：IAIApi(ai.yun.139.com) 的 assistant/knowledge/personal/v2/base/*
    '/richlifeApp/knowledgeBase':             ('ai',   'assistant/knowledge/personal/v2/base'),
    # RSA 公钥：IAuthenticationApi @ AuthenticationRetrofitFactory
    '/richlifeApp/aiDirectory/api/getRsaPublicKey': ('auth', 'openapi/authentication/key/getRsaPublicKey'),
    # 个人动态：IDynamicApi @ DynamicRetrofitFactory (huidu-middle/openapi)
    '/richlifeApp/personalDynamic/queryPersonalDynamic': ('dynamic', 'pDynamicInfo/pagePersonalDynamicMedia'),
    '/richlifeApp/personalDynamic/queryFileSchedules':   ('dynamic', 'pDynamicInfo/queryBatchList'),

    # ── 未知对应 / 待人工确认：见 APP-ENDPOINT-MAP.md ─────────────────────
    # aiDirectory/*（通讯录）      -> icloud contactsdk，未在 decomp 提取到 retrofit 注解
    # note/*, notebook/*           -> note-njs SDK，注解用常量拼接，未提取到
    # api/openclaw/*               -> AlgorithmCenterMClawApi 无 photoOrganize/deduplicate/session 路径
    # personalDynamic/*            -> 未提取到对应 retrofit
    # api/llm/networkSearch        -> 未提取到对应 retrofit
}


# ---------------------------------------------------------------------------
# .env 兜底读取：CM_CLOUD_SESSION_FILE 允许直接写在 .env 里，
# 部署时无需外部注入环境变量。优先级：os.environ > common_auth/.env >
# mclaw/api/.env > CM_CLOUD_ENV_FILE。
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent      # .../common/mclaw/api
_PACK_ROOT = _HERE.parents[2]                # .../cloud_skills_pack_app


def _env_file_candidates() -> List[str]:
    """按优先级返回实际存在的 .env 路径。"""
    paths: List[str] = [
        str(_PACK_ROOT / 'common_auth' / '.env'),
        str(_HERE / '.env'),
    ]
    extra = (os.getenv('CM_CLOUD_ENV_FILE') or '').strip()
    if extra:
        paths.append(extra)
    return [p for p in paths if p and os.path.exists(p)]


def env_value(key: str, default: str = '') -> str:
    """读配置：``os.environ`` 优先，缺失时回落到打包内的 ``.env``。"""
    value = (os.getenv(key) or '').strip()
    if value:
        return value
    try:
        from dotenv import dotenv_values
    except Exception:
        return default
    for path in _env_file_candidates():
        try:
            got = dotenv_values(path).get(key)
        except Exception:
            got = None
        if got:
            return str(got).strip()
    return default


def resolve_endpoint(host: str, path: str) -> Tuple[str, str]:
    """把 (host, path) 改写成 APK 原生端点；未登记映射时原样返回。"""
    key = path if path.startswith('/') else '/' + path
    hit: Optional[Tuple[str, str]] = ENDPOINT_MAP.get(key)
    if not hit:
        return host, path
    host_key, app_path = hit
    return HOSTS[host_key], app_path


def resolve_url(host: str, path: str) -> str:
    """把 (host, path) 拼成完整 URL（内部先过 ``resolve_endpoint`` 改写）。

    供不走 ``_BaseApi`` 的裸 HTTP 调用点复用（相册/通讯录/群组/笔记/会话
    文件夹等）。
    """
    resolved_host, resolved_path = resolve_endpoint(host, path)
    return resolved_host.rstrip('/') + '/' + resolved_path.lstrip('/')


# ---------------------------------------------------------------------------
# APK 原生鉴权头（通用模式：任意 IP 可用，等价 mcsapi CloudAuthInterceptor）
#
# 真机抓包（移动云盘抓包.zip）证实：业务网关上每请求必需
#   Authorization: Basic base64("mobile:" + account + ":" + token)
#   x-yun-api-version / x-yun-client-info / x-yun-device-id / x-yun-user-agent /
#   x-yun-app-channel / x-yun-net-type / x-yun-svc-type / x-yun-module-type /
#   x-yun-uni / x-yun-tid  +  Accept-Language / Content-Type / User-Agent
# 缺任意一项会得到 04000014(系统服务调用错误) 或 04000005(认证失败)。
# ---------------------------------------------------------------------------
NATIVE_APP_CHANNEL = '10000023'
NATIVE_USER_AGENT = 'android|2203121C|android 13|mCloud13.2.4-032'
NATIVE_DEVICE_TEMPLATE = (
    '1|127.0.0.1|1|13.2.4|Xiaomi|2203121C|{device_id}|02-00-00-00-00-00|'
    'android 13|1080X2319|zh||||032|0|2274fd15daeabca5|'
)
NATIVE_HTTP_UA = 'okhttp/4.12.0'
DEFAULT_API_VERSION = 'v1'

# 真机抓包口径：仅 file/list 用 v2；实测 v1 亦可，故默认全局 v1，按需覆盖。
API_VERSION_BY_PATH: Dict[str, str] = {
    'file/list': 'v2',
    'recyclebin/list': 'v1',
}


def api_version_for(path: str = '', default: str = '') -> str:
    """返回该 path 的 ``x-yun-api-version``；未登记时用 ``CM_CLOUD_API_VERSION`` 或默认 ``v1``。"""
    key = str(path or '').strip().lstrip('/')
    for suffix, version in API_VERSION_BY_PATH.items():
        if key == suffix or key.endswith('/' + suffix):
            return version
    override = env_value('CM_CLOUD_API_VERSION')
    return override or default or DEFAULT_API_VERSION


def session_file_path() -> str:
    """会话文件路径（``CM_CLOUD_SESSION_FILE``，其次包内 ``common_auth/session.json``）。

    相对路径按包根目录解析，便于整包搬迁后免改配置。
    """
    packaged = _PACK_ROOT / 'common_auth' / 'session.json'
    path = (env_value('CM_CLOUD_SESSION_FILE') or '').strip()
    if path:
        cand = Path(path)
        if not cand.is_absolute():
            cand = _PACK_ROOT / path.lstrip('./\\')
        if cand.exists():
            return str(cand)
    if packaged.exists():
        return str(packaged)
    return path


def load_session(path: str = '') -> Dict[str, Any]:
    """读取登录脚本产出的会话文件（含 account / userDomainId / deviceId / token / authHeader）。"""
    import json
    target = path or session_file_path()
    if not target or not os.path.exists(target):
        raise RuntimeError(
            '通用(app)后端需要会话文件：请设置 CM_CLOUD_SESSION_FILE，'
            '或把 session.json 放到 common_auth/session.json。'
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
        raise RuntimeError('会话文件缺少 authHeader，且 account/token 不完整。')
    raw = 'mobile:%s:%s' % (account, token)
    return 'Basic ' + base64.b64encode(raw.encode('utf-8')).decode('ascii')


def build_native_headers(session: Optional[Dict[str, Any]] = None, path: str = '',
                         version: str = '') -> Dict[str, str]:
    """构造 APK 原生业务请求头（通用模式，任意 IP 可用）。"""
    s = session if isinstance(session, dict) and session else load_session()
    device = NATIVE_DEVICE_TEMPLATE.format(device_id=str(s.get('deviceId') or ''))
    uni = str(s.get('userDomainId') or s.get('userid') or '').strip()
    channel = env_value('CM_CLOUD_APP_CHANNEL') or NATIVE_APP_CHANNEL
    return {
        'x-yun-api-version': version or api_version_for(path),
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


# APK 里不存在对应实现的 Open API 路径（这些接口在本包中不可用）。
APP_UNSUPPORTED_PATHS: Tuple[str, ...] = (
    '/richlifeApp/aiDirectory/api/getContactInfos',
    '/richlifeApp/aiService/api/image/alivePhoto',
    '/richlifeApp/aiService/api/image/avatar/cartoon',
    '/richlifeApp/aiService/api/image/beautify/face',
    '/richlifeApp/aiService/api/image/caption',
    '/richlifeApp/aiService/api/image/deduplicate',
    '/richlifeApp/aiService/api/image/edit/babyTimeMachine',
    '/richlifeApp/aiService/api/image/edit/faceAnime',
    '/richlifeApp/aiService/api/image/edit/gabyGrowthPrediction',
    '/richlifeApp/aiService/api/image/edit/imageCutout',
    '/richlifeApp/aiService/api/image/expand',
    '/richlifeApp/aiService/api/image/restore/oldPhoto',
    '/richlifeApp/aiService/api/image/textToImage',
    '/richlifeApp/api/image/asyncSelectPhoto',
    '/richlifeApp/api/image/selectPhotoResult',
    '/richlifeApp/api/llm/networkSearch',
    '/richlifeApp/api/openclaw/deduplicate/result',
    '/richlifeApp/api/openclaw/deduplicate/submit',
    '/richlifeApp/api/openclaw/photoOrganize/task',
    '/richlifeApp/api/openclaw/photoOrganize/task/query',
    '/richlifeApp/api/openclaw/photoOrganize/task/retry',
    '/richlifeApp/api/openclaw/session/folder/name',
    '/richlifeApp/personalSaas/file/batchCopy',
)


def is_app_supported(path: str) -> bool:
    """本包是否有该 Open API 路径的原生实现。"""
    key = path if str(path).startswith('/') else '/' + str(path)
    if key in APP_UNSUPPORTED_PATHS:
        return False
    return key in ENDPOINT_MAP


__all__ = [
    'HOSTS', 'ENDPOINT_MAP',
    'resolve_endpoint', 'resolve_url', 'env_value',
    'NATIVE_APP_CHANNEL', 'NATIVE_USER_AGENT', 'NATIVE_DEVICE_TEMPLATE',
    'API_VERSION_BY_PATH', 'api_version_for', 'session_file_path',
    'load_session', 'build_native_headers', 'APP_UNSUPPORTED_PATHS',
    'is_app_supported',
]
