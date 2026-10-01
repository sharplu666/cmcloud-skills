#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国移动云盘群组 Open API CLI。"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from requests import exceptions as req_exc

# -------------------------------------------------------------------------
# 模块路径初始化与鉴权导入
# -------------------------------------------------------------------------
COMMON_AUTH_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common_auth'))
if COMMON_AUTH_ROOT not in sys.path:
    sys.path.insert(0, COMMON_AUTH_ROOT)

_MCLAW_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'common'))
if _MCLAW_ROOT not in sys.path:
    sys.path.insert(0, _MCLAW_ROOT)

from cm_cloud_auth import (
    get_auth_header,
    get_skill_auth,
    group_circle_open_api_headers,
    group_circle_publish_device_id,
)
from cli_timing import (
    clear_api_timings,
    flush_cli_output_buffer,
    record_api_timing,
    start_cli_output_buffer,
    write_cli_output_line,
)
from cli_trace import (
    clear_last_trace_id,
    set_last_api_path,
    set_last_trace_id,
    snapshot_trace_id,
)
from mclaw.shared.cm_cloud.cli_validate import validate_cloud_file_ids
from mclaw.shared.cm_cloud.category_token import category_render_token
from mclaw.shared.cm_cloud.cli_jsonl import emit_error as _emit_error_jsonl
from mclaw.shared.cm_cloud.cli_jsonl import emit_jsonl
from mclaw.shared.cm_cloud.mclaw_jsonl import persist_flushed_stdout
from mclaw.shared.cm_cloud.session_cli_validate import format_runtime_env_line
from mclaw.api import ApiDispatcher
from mclaw.api.app_endpoint_map import resolve_url
from mclaw.api.album._models import PageInfo
from mclaw.api.album.photo_customization_file_list_api import (
    PhotoCustomizationFileListRequest,
)
from mclaw.api.album.story_memory_file_list_api import StoryMemoryFileListRequest
from mclaw.shared.cm_cloud.personal_service import batch_get as _personal_batch_get


_batch_get_dispatcher: Optional[ApiDispatcher] = None
_album_dispatcher: Optional[ApiDispatcher] = None


def api_batch_get(file_ids, thumbnail_styles=None):
    """批量获取个人云文件详情（本 skill Service 层）。"""
    global _batch_get_dispatcher
    if _batch_get_dispatcher is None:
        _batch_get_dispatcher = ApiDispatcher(host=HOST, auth_fn=get_auth_header)
    return _personal_batch_get(_batch_get_dispatcher, file_ids, thumbnail_styles=thumbnail_styles)


def get_album_dispatcher() -> ApiDispatcher:
    """相册列表查询用 dispatcher（叶子 API 自带相册鉴权头）。"""
    global _album_dispatcher
    if _album_dispatcher is None:
        _album_dispatcher = ApiDispatcher(host=HOST, auth_fn=get_auth_header)
    return _album_dispatcher

# -------------------------------------------------------------------------
# 全局常量定义
# -------------------------------------------------------------------------
_skill_auth = get_skill_auth()
HOST = str(_skill_auth.host or '').strip().rstrip('/')
APP_ID = str(_skill_auth.app_id or '').strip()

# 退出码规范
EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_BUSINESS_ERROR = 2
EXIT_INTERNAL_ERROR = 3

REQUEST_TIMEOUT_SEC = 60

# 列表与翻页限制
MAX_ALBUM_ADD_IDS = 500
MAX_LIST_FETCH_PAGES = 2000
LIST_START_PAGE = 1
LIST_PAGE_SIZE_GROUP = 10
SEARCH_GROUP_PER_PAGE = 100
ALBUM_FILE_LIST_PAGE_SIZE = 50
PUBLISH_ALBUM_TYPE_ALBUM = 'album'
PUBLISH_ALBUM_TYPE_MEMORY = 'memory'
PUBLISH_ALBUM_TYPE_CHOICES = frozenset({
    PUBLISH_ALBUM_TYPE_ALBUM,
    PUBLISH_ALBUM_TYPE_MEMORY,
})

# 发布动态相关枚举
PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE = '0'
PUBLISH_CIRCLE_DYNAMIC_TYPE_IMAGE = '1'
PUBLISH_CIRCLE_DYNAMIC_TYPE_VIDEO = '2'
PUBLISH_CIRCLE_DYNAMIC_TYPE_CHOICES = frozenset({
    PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE,
    PUBLISH_CIRCLE_DYNAMIC_TYPE_IMAGE,
    PUBLISH_CIRCLE_DYNAMIC_TYPE_VIDEO,
})

PUBLISH_CIRCLE_ASSERT_CONTENT_TYPE_FILE = 1
PUBLISH_CIRCLE_ASSERT_CONTENT_TYPE_FOLDER = 2

# 重试策略
PUBLISH_CIRCLE_MAX_ATTEMPTS = 3
PUBLISH_CIRCLE_RETRY_BASE_SEC = 1.0
PUBLISH_CIRCLE_RETRY_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})

# 权限枚举映射
PERMISSION_TYPE_LABELS: Dict[int, str] = {
    1: '全权限',
    2: '分享权限',
    3: '查看',
    4: '定制',
}

API_PATH_MY_JOIN = '/richlifeApp/devapp/hcy/group/manage/myJoinList'
API_PATH_MY_CREATE = '/richlifeApp/devapp/hcy/group/manage/myCreateGroupList'
API_PATH_SEARCH_GROUP = '/richlifeApp/devapp/manage/search/searchGroup/v5'
API_PATH_PUBLISH = '/richlifeApp/devapp/circle/publishCircle'
API_PATH_QUERY_MULTI_TASK = '/richlifeApp/devapp/hcy/group/dynamic/assets/queryMultiTaskStatus'

# 任务状态枚举
TASK_STATUS_PROCESSING = 0   # 处理中
TASK_STATUS_SUCCESS = 1      # 处理成功
TASK_STATUS_FAILED = 2       # 处理失败
TASK_STATUS_PARTIAL = 3      # 部分成功
TASK_STATUS_CANCELLED = 4    # 用户取消

TASK_STATUS_TEXT = {
    0: '处理中',
    1: '处理成功',
    2: '处理失败',
    3: '部分成功',
    4: '用户取消',
}

TASK_POLL_INTERVAL_SEC = 3   # 轮询间隔
TASK_POLL_MAX_ATTEMPTS = 20  # 最大轮询次数（60 秒超时）


# -------------------------------------------------------------------------
# 基础工具与输出打印
# -------------------------------------------------------------------------
def emit_group_path_card(*, group_id: str, group_name: str = '') -> None:
    """发布成功回执：:::groupPath（末行 meta 走 card_meta 配置）。"""
    from mclaw.shared.cm_cloud.card import Card

    row = {
        'groupId': str(group_id or ''),
        'groupName': str(group_name or ''),
        'button': '去查看',
        'pretext': '已为您发布到：',
    }
    for line in Card('groupPath', [row], cli='publish_circle').generate():
        write_cli_output_line(line)


def print_json_line(data: dict) -> None:
    """以 JSONL 输出至 stdout（字段序与 trace 注入见 ``cli_jsonl``）。"""
    emit_jsonl(data, write_line=write_cli_output_line)


def emit_input_error(message: str) -> int:
    """参数/用法错误：结构化 JSONL，退出码 1。"""
    return _emit_error_jsonl(
        f'错误：{message}',
        code=EXIT_INPUT_ERROR,
        from_api=False,
        write_line=write_cli_output_line,
    )


def print_verbose_log(verbose: bool, message: str) -> None:
    """输出调试信息至标准错误流。"""
    if verbose:
        print(f'[verbose] {message}', file=sys.stdout, flush=True)


def is_api_success(body: Dict[str, Any]) -> bool:
    """判断接口响应是否成功。"""
    # 兼容两类返回协议：
    # 1) {"success": true, "code": 0}
    # 2) {"resultCode": 0, "message": "ok"}
    if 'success' in body:
        if not bool(body.get('success')):
            return False
        code = body.get('code')
        if code is None:
            return True
        return code == 0 or str(code) in ('0', '0000')

    if 'resultCode' in body:
        result_code = body.get('resultCode')
        return result_code == 0 or str(result_code) in ('0', '0000')

    # 未识别的协议，按失败处理，避免误判
    return False


def format_permission_type_text(value: Any) -> Optional[str]:
    """转换 permissionType 为中文描述。"""
    try:
        return PERMISSION_TYPE_LABELS.get(int(str(value).strip()))
    except (TypeError, ValueError):
        return None


def get_api_message(body: Dict[str, Any], default: str = '业务失败') -> str:
    """提取接口 message 字段，兼容 message/msg。"""
    message = body.get('message') or body.get('msg') or default
    return str(message)


def get_api_code(body: Dict[str, Any]) -> Any:
    """提取接口 code 字段，兼容 code/resultCode。"""
    if 'code' in body:
        return body.get('code')
    return body.get('resultCode')


def is_publish_permission_denied(message: str) -> bool:
    """判断错误信息是否属于权限不足。"""
    msg_lower = str(message).lower()
    zh_keywords = ('无权限', '没有权限', '权限不足', '无发布权限', '发布权限', '未授权', '鉴权失败')
    en_keywords = ('permission', 'denied', 'forbid', 'http 403', ' 403:')
    
    return any(x in str(message) for x in zh_keywords) or \
           any(x in msg_lower for x in en_keywords)


# -------------------------------------------------------------------------
# API 客户端封装
# -------------------------------------------------------------------------
class GroupCircleAPIClient:
    """处理群组 Open API 通信。"""

    def __init__(self, verbose: bool = False):
        self.host = HOST
        self.headers = dict(group_circle_open_api_headers(APP_ID))
        self.device_id = str(group_circle_publish_device_id())
        self.verbose = verbose

    @staticmethod
    def _extract_error_message(response: Optional[requests.Response]) -> str:
        """从 HTTP 响应中提取错误信息。"""
        if response is None:
            return ''
        body_text = (response.text or '').strip()
        if not body_text:
            return f"HTTP {response.status_code}"
            
        try:
            body = response.json()
            if isinstance(body, dict):
                for key in ('message', 'msg'):
                    if value := body.get(key):
                        if str(value).strip():
                            return str(value)
        except ValueError:
            pass
        return body_text

    def _post(self, path: str, payload: Dict[str, Any], max_attempts: int = 1) -> Dict[str, Any]:
        """核心 POST 请求封装，支持可配置的重试策略。"""
        set_last_api_path(path)
        url = resolve_url(self.host, path)
        
        for attempt in range(1, max_attempts + 1):
            delay = PUBLISH_CIRCLE_RETRY_BASE_SEC * (2 ** (attempt - 1))
            started = time.perf_counter()
            try:
                resp = requests.post(url, json=payload, headers=self.headers, timeout=REQUEST_TIMEOUT_SEC)
                record_api_timing(path, (time.perf_counter() - started) * 1000, attempt=attempt - 1, max_attempts=max_attempts)
                set_last_trace_id(resp)

                # 状态码非 200 处理
                if resp.status_code != 200:
                    error_msg = self._extract_error_message(resp)
                    if resp.status_code in PUBLISH_CIRCLE_RETRY_HTTP_STATUS and attempt < max_attempts:
                        print_verbose_log(self.verbose, f'HTTP {resp.status_code} 异常，{delay:.1f}s 后第 {attempt+1} 次重试')
                        time.sleep(delay)
                        continue
                    raise RuntimeError(error_msg or f'HTTP {resp.status_code}')

                # 响应解析
                try:
                    return resp.json()
                except json.JSONDecodeError as e:
                    if attempt < max_attempts:
                        print_verbose_log(self.verbose, f'响应非 JSON，{delay:.1f}s 后第 {attempt+1} 次重试: {e}')
                        time.sleep(delay)
                        continue
                    raise RuntimeError(f'响应非 JSON: {e}') from e
                    
            except (req_exc.Timeout, req_exc.ConnectionError) as e:
                record_api_timing(path, (time.perf_counter() - started) * 1000, attempt=attempt - 1, max_attempts=max_attempts)
                if attempt < max_attempts:
                    print_verbose_log(self.verbose, f'网络异常，{delay:.1f}s 后第 {attempt+1} 次重试: {e}')
                    time.sleep(delay)
                    continue
                clear_last_trace_id()
                raise RuntimeError(f'请求失败: {e}') from e

        raise RuntimeError("超出最大重试次数")

    def get_my_join_list(self, page_number: int, page_size: int) -> Dict[str, Any]:
        """查询我加入的群组。"""
        return self._post(API_PATH_MY_JOIN, {'pageNumber': page_number, 'pageSize': page_size})

    def get_my_create_group_list(self, page_number: int, page_size: int) -> Dict[str, Any]:
        """查询我创建的群组。"""
        return self._post(API_PATH_MY_CREATE, {'pageNumber': page_number, 'pageSize': page_size})

    def publish_circle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """发布群组动态，带自动重试。"""
        return self._post(API_PATH_PUBLISH, payload, max_attempts=PUBLISH_CIRCLE_MAX_ATTEMPTS)

    def query_multi_task_status(self, task_id_list: List[str]) -> Dict[str, Any]:
        """查询多个任务状态"""
        return self._post(API_PATH_QUERY_MULTI_TASK, {'taskIDList': task_id_list})

    def search_group(
        self,
        keywords: str,
        per_page: int,
        page_after: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """按关键词搜索群组。"""
        payload: Dict[str, Any] = {
            'conditions': {
                'keywords': keywords,
            },
            'showInfo': {
                'pageAfter': list(page_after) if page_after else [],
                'perPage': per_page,
            },
            'requestId': f'req_{uuid.uuid4().hex}',
        }
        return self._post(API_PATH_SEARCH_GROUP, payload)


# -------------------------------------------------------------------------
# 数据解析与业务逻辑封装
# -------------------------------------------------------------------------
def normalize_circle_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """标准化群组列表单条记录字段。"""
    pt = raw.get('permissionType')
    return {
        'groupId': raw.get('id'),
        'type': raw.get('type'),
        'iconUrl': str(raw.get('iconUrl') or ''),
        'name': str(raw.get('name') or ''),
        'topicId': raw.get('topicId'),
        'topicName': str(raw.get('topicName') or '') or None,
        'memberNum': raw.get('memberNum'),
        'permissionType': pt,
        'permissionTypeText': format_permission_type_text(pt),
        'backgroundUrl': str(raw.get('backgroundUrl') or '') or None,
        'userPermissionType': raw.get('userPermissionType'),
        'creatorAccountUserId': str(raw.get('creatorAccountUserId') or ''),
        'managerAccountUserId': str(raw.get('managerAccountUserId') or '') or None,
        'joinGroupTime': str(raw.get('joinGroupTime') or '') or None,
        'createTime': str(raw.get('createTime') or '') or None,
        'dynamicUpdateTime': str(raw.get('dynamicUpdateTime') or '') or None,
        'groupTopFlag': raw.get('groupTopFlag'),
        'groupTopTime': str(raw.get('groupTopTime') or '') or None,
        'sponsorStatus': raw.get('sponsorStatus'),
    }


def strip_group_name_markup(value: Any) -> str:
    """去掉搜索高亮标签，得到可展示的群名。"""
    return re.sub(r'</?keywordsTag>', '', str(value or '')).strip()


def normalize_search_group_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """标准化群组搜索结果单条记录字段。"""
    pt = raw.get('permissionType')
    return {
        'groupId': str(raw.get('groupId') or ''),
        'icon': str(raw.get('icon') or '') or None,
        'name': str(raw.get('name') or ''),
        'backgroundUrl': str(raw.get('backgroudUrl') or raw.get('backgroundUrl') or '') or None,
        'type': raw.get('type'),
        'managerAccount': str(raw.get('managerAccount') or '') or None,
        'managerUserId': str(raw.get('managerUserId') or '') or None,
        'groupNo': str(raw.get('groupNo') or '') or None,
        'verifyStatus': raw.get('verifyStatus'),
        'openType': str(raw.get('openType') or '') or None,
        'topicId': str(raw.get('topicId') or '') or None,
        'topicName': str(raw.get('topicName') or '') or None,
        'permissionType': pt,
        'permissionTypeText': format_permission_type_text(pt),
        'memberNum': str(raw.get('memberNum') or '') or None,
        'accountExisting': raw.get('accountExisting'),
    }


def search_keyword_variants(keywords: str) -> List[str]:
    """含空格时同时搜原词与去空格；无空格则只搜一次。"""
    stripped = str(keywords or '').strip()
    if not stripped:
        return []
    compact = ''.join(stripped.split())
    if compact and compact != stripped:
        return [stripped, compact]
    return [stripped]


def merge_search_group_rows(row_lists: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    seen = set()
    merged: List[Dict[str, Any]] = []
    for rows in row_lists:
        for row in rows:
            gid = str(row.get('groupId') or '').strip()
            key = gid or str(row.get('name') or '')
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def fetch_search_group_pages(
    client: 'GroupCircleAPIClient',
    keywords: str,
) -> Dict[str, Any]:
    """拉全部分页。ok=False 时带 error（可直接 print_json_line）与 exit_code。"""
    all_rows: List[Dict[str, Any]] = []
    page_after: Optional[List[Any]] = None
    fetches = 0
    total_count: Optional[int] = None

    while fetches < MAX_LIST_FETCH_PAGES:
        fetches += 1
        try:
            body = client.search_group(
                keywords=keywords,
                per_page=SEARCH_GROUP_PER_PAGE,
                page_after=page_after,
            )
        except RuntimeError as e:
            return {
                'ok': False,
                'exit_code': EXIT_BUSINESS_ERROR,
                'error': {'record': 'error', 'status': 'error', 'message': str(e), '_from_api': True},
                'rows': [],
                'fetches': fetches,
            }
        except Exception as e:
            return {
                'ok': False,
                'exit_code': EXIT_INTERNAL_ERROR,
                'error': {'record': 'error', 'status': 'error', 'message': str(e)},
                'rows': [],
                'fetches': fetches,
            }

        if not is_api_success(body):
            msg = get_api_message(body)
            return {
                'ok': False,
                'exit_code': EXIT_BUSINESS_ERROR,
                'error': {
                    'record': 'error',
                    'status': 'error',
                    'message': str(msg),
                    'code': get_api_code(body),
                    '_from_api': True,
                },
                'rows': [],
                'fetches': fetches,
            }

        data = body.get('data') or {}
        if total_count is None:
            try:
                total_count = int(data.get('count')) if data.get('count') is not None else None
            except (TypeError, ValueError):
                total_count = None

        raw_rows = data.get('groupRows') or []
        rows = [normalize_search_group_row(x) for x in raw_rows if isinstance(x, dict)]
        all_rows.extend(rows)

        next_page_after = data.get('pageAfter')
        if not isinstance(next_page_after, list) or not rows:
            page_after = next_page_after if isinstance(next_page_after, list) else None
            break
        page_after = next_page_after
    else:
        return {
            'ok': False,
            'exit_code': EXIT_BUSINESS_ERROR,
            'error': {
                'record': 'error',
                'status': 'error',
                'message': f'自动翻页超过上限 {MAX_LIST_FETCH_PAGES} 次，请缩小范围或联系维护',
            },
            'rows': [],
            'fetches': fetches,
        }

    return {
        'ok': True,
        'rows': all_rows,
        'total_count': total_count,
        'fetches': fetches,
        'page_after': page_after,
    }


def _ensure_album_list_ok(resp: Any, action: str) -> None:
    if getattr(resp, 'success', False):
        return
    msg = str(getattr(resp, 'message', '') or '').strip() or '业务失败'
    raise RuntimeError(f'{action}失败: {msg}')


def fetch_album_file_ids(album_id: str, album_type: str) -> Tuple[List[str], int, bool]:
    """按相册类型分页拉取册内 fileId，最多 ``MAX_ALBUM_ADD_IDS`` 条。

    ``album`` → 自定义相册列表接口；``memory`` → 回忆故事列表接口。
    超过上限截断为前 ``MAX_ALBUM_ADD_IDS`` 个（默认拍摄/上传时间倒序）。
    返回 ``(fileIds, totalCount, truncated)``。
    """
    aid = str(album_id or '').strip()
    kind = str(album_type or '').strip()
    if not aid:
        raise ValueError('album-id 不能为空')
    if kind not in PUBLISH_ALBUM_TYPE_CHOICES:
        raise ValueError('album-type 仅支持 album（自定义相册）或 memory（回忆故事）')

    dispatcher = get_album_dispatcher()
    cursor = ''
    content_ids: List[str] = []
    seen = set()
    total_count = 0
    is_memory = kind == PUBLISH_ALBUM_TYPE_MEMORY
    action = '查询故事相册文件' if is_memory else '查询自定义相册文件'

    for _ in range(MAX_LIST_FETCH_PAGES):
        page_info = PageInfo(
            pageCursor=cursor,
            pageSize=ALBUM_FILE_LIST_PAGE_SIZE,
            needTotalCount=1,
        )
        try:
            if is_memory:
                resp = dispatcher.album.story_memory_file_list(
                    StoryMemoryFileListRequest(
                        albumId=aid,
                        pageInfo=page_info,
                        orderBy='1',
                        orderDirection='1',
                    ),
                )
            else:
                resp = dispatcher.album.photo_customization_file_list(
                    PhotoCustomizationFileListRequest(
                        albumId=aid,
                        pageInfo=page_info,
                        imageThumbnailStyleList=['Big'],
                        orderBy=1,
                        orderDirection='1',
                    ),
                )
        except Exception as e:
            raise RuntimeError(f'{action}失败: {e}') from e
        _ensure_album_list_ok(resp, action)

        if not total_count:
            try:
                total_count = int(getattr(resp, 'total_count', 0) or 0)
            except (TypeError, ValueError):
                total_count = 0

        page_rows = list(resp.file_list or [])
        for idx, item in enumerate(page_rows):
            file_id = str(getattr(item, 'file_id', '') or '').strip()
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            content_ids.append(file_id)
            if len(content_ids) >= MAX_ALBUM_ADD_IDS:
                next_cursor = str(getattr(resp, 'next_page_cursor', '') or '').strip()
                more_in_page = any(
                    str(getattr(later, 'file_id', '') or '').strip()
                    and str(getattr(later, 'file_id', '') or '').strip() not in seen
                    for later in page_rows[idx + 1:]
                )
                truncated = bool(
                    more_in_page
                    or next_cursor
                    or (total_count > MAX_ALBUM_ADD_IDS)
                )
                return content_ids, total_count or len(content_ids), truncated

        next_cursor = str(getattr(resp, 'next_page_cursor', '') or '').strip()
        if not next_cursor or next_cursor == cursor or not page_rows:
            return content_ids, total_count or len(content_ids), False
        cursor = next_cursor

    raise RuntimeError(f'相册文件列表翻页超过上限 {MAX_LIST_FETCH_PAGES} 次')


def parse_publish_args(args: argparse.Namespace) -> Tuple[List[str], List[int]]:
    """解析并校验发布动态所需的 fileid / file-type-list 参数。"""
    ids = [x.strip() for x in str(args.fileid or '').replace('，', ',').split(',') if x.strip()]
    if not ids:
        raise ValueError('fileid 不能为空')
    if len(ids) > MAX_ALBUM_ADD_IDS:
        raise ValueError(f'fileid 最多 {MAX_ALBUM_ADD_IDS} 个')
    ids = validate_cloud_file_ids(ids, context='fileid')

    type_raw = [x.strip() for x in (args.file_type_list or '').replace('，', ',').split(',') if x.strip()]
    if not type_raw:
        types = [PUBLISH_CIRCLE_ASSERT_CONTENT_TYPE_FILE] * len(ids)
    else:
        if len(type_raw) != len(ids):
            raise ValueError('file-type-list 的数量必须与 fileid 一致')
        if not all(x in ('1', '2') for x in type_raw):
            raise ValueError('file-type-list 仅支持 1(文件) 或 2(文件夹)')
        types = [int(x) for x in type_raw]

    return ids, types


def resolve_publish_attachments(
    args: argparse.Namespace,
) -> Tuple[List[str], List[int], Dict[str, Any]]:
    """``--fileid`` 与 ``--album-id`` 二选一；相册路径内部展开为 fileId 再发布。"""
    album_id = str(getattr(args, 'album_id', '') or '').strip()
    album_type = str(getattr(args, 'album_type', '') or '').strip()
    fileid_raw = str(getattr(args, 'fileid', '') or '').strip()
    type_list_raw = str(getattr(args, 'file_type_list', '') or '').strip()

    if album_id and fileid_raw:
        raise ValueError('--album-id 与 --fileid 不能同时使用')
    if not album_id and not fileid_raw:
        raise ValueError('须提供 --fileid 或 --album-id')
    if album_id:
        if album_type not in PUBLISH_ALBUM_TYPE_CHOICES:
            raise ValueError('--album-id 须同时指定 --album-type album|memory')
        if type_list_raw:
            raise ValueError('--album-id 不能与 --file-type-list 同时使用')
        ids, total_count, truncated = fetch_album_file_ids(album_id, album_type)
        if not ids:
            raise ValueError('相册内没有可发布的图片')
        types = [PUBLISH_CIRCLE_ASSERT_CONTENT_TYPE_FILE] * len(ids)
        extra = {
            'albumId': album_id,
            'albumType': album_type,
            'albumTotalCount': total_count,
            'albumTruncated': truncated,
        }
        return ids, types, extra
    if album_type:
        raise ValueError('--album-type 仅可与 --album-id 同时使用')
    ids, types = parse_publish_args(args)
    return ids, types, {}


def infer_dynamic_type_for_publish(
    content_ids: List[str],
    content_assert_types: List[int],
) -> str:
    """根据 fileid 在云盘 batchGet 的 category 推断 dynamicType（与接口枚举一致）。

    - 任一条附件为文件夹(contentType=2) → 文件动态 0
    - 仅文件附件：全部为图片 →1；全部为视频 →2；否则（混合或文档/音频等）→0
    """
    if len(content_ids) != len(content_assert_types):
        raise ValueError('推断动态类型失败：fileid 与附件类型数量不一致')

    if any(t == PUBLISH_CIRCLE_ASSERT_CONTENT_TYPE_FOLDER for t in content_assert_types):
        return PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE

    file_entries = [
        cid
        for cid, t in zip(content_ids, content_assert_types)
        if t == PUBLISH_CIRCLE_ASSERT_CONTENT_TYPE_FILE
    ]
    if not file_entries:
        return PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE

    tokens: List[str] = []
    for i in range(0, len(file_entries), 100):
        chunk = file_entries[i : i + 100]
        rows = api_batch_get(chunk, thumbnail_styles=None)
        by_id: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if str(row.get('errCode') or '') != '0000':
                continue
            sf = row.get('srcFile')
            if isinstance(sf, dict):
                fid = str(sf.get('fileId') or '').strip()
                if fid:
                    by_id[fid] = sf
        for fid in chunk:
            if fid not in by_id:
                raise RuntimeError(f'推断动态类型失败：batchGet 未返回 fileId={fid!r} 的文件详情')
            tokens.append(category_render_token(by_id[fid].get('category')))

    if not tokens:
        return PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE

    if all(t == 'image' for t in tokens):
        return PUBLISH_CIRCLE_DYNAMIC_TYPE_IMAGE
    if all(t == 'video' for t in tokens):
        return PUBLISH_CIRCLE_DYNAMIC_TYPE_VIDEO
    return PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE


def emit_publish_error(message: str, code: Any = None) -> int:
    """输出发布失败的标准错误 JSONL 并返回业务错误码。"""
    rec: Dict[str, Any] = {
        'record': 'error',
        'status': 'error',
        'message': str(message),
        '_from_api': True,
    }
    if code is not None:
        rec['code'] = code
        
    if is_publish_permission_denied(str(message)):
        rec['hint'] = (
            '可能被接口判定为权限不足，当前账号可能不具备在该群组发布动态的权限。'
            '请对照 my_join_list / my_create_group_list 输出中的 permissionType 与 permissionTypeText。'
        )
        
    print_json_line(rec)
    return EXIT_BUSINESS_ERROR


def process_paged_list(
    command_name: str, 
    fetch_func: Callable[[int, int], Dict[str, Any]], 
    verbose: bool
) -> int:
    """处理自动翻页列表请求，输出格式化 JSONL。"""
    all_rows: List[Dict[str, Any]] = []
    page = LIST_START_PAGE
    total, pages_total, last_page_num = None, None, page
    fetches = 0
    trace_locked = False

    while fetches < MAX_LIST_FETCH_PAGES:
        fetches += 1
        print_verbose_log(verbose, f'{command_name} 自动翻页 第{fetches}次请求 page={page} pageSize={LIST_PAGE_SIZE_GROUP}')
        
        try:
            body = fetch_func(page, LIST_PAGE_SIZE_GROUP)
        except RuntimeError as e:
            print_json_line({'record': 'error', 'status': 'error', 'message': str(e), '_from_api': True})
            return EXIT_BUSINESS_ERROR
        except Exception as e:
            print_json_line({'record': 'error', 'status': 'error', 'message': str(e)})
            return EXIT_INTERNAL_ERROR

        if not is_api_success(body):
            msg = get_api_message(body)
            print_json_line({
                'record': 'error',
                'status': 'error',
                'message': str(msg),
                'code': get_api_code(body),
                '_from_api': True,
            })
            return EXIT_BUSINESS_ERROR

        if not trace_locked:
            snapshot_trace_id()
            trace_locked = True

        # 数据提取
        data = body.get('data') or {}
        pinfo = data.get('pageInfo') or {}
        raw_list = pinfo.get('list') or []
        
        if total is None:
            total = int(pinfo.get('total') or 0)
            pages_total = pinfo.get('pages')

        # 记录转换
        all_rows.extend([normalize_circle_row(x) for x in raw_list if isinstance(x, dict)])

        # 翻页游标判断
        if pinfo.get('isLastPage') is True or not raw_list:
            break

        try:
            pn = int(pinfo.get('pageNumber') or page)
            pg = int(pinfo.get('pages') or 0)
        except (TypeError, ValueError):
            pn, pg = page, 0
            
        last_page_num = pn
        if pg and pn >= pg:
            break
            
        page = pn + 1
    else:
        print_json_line({
            'record': 'error', 'status': 'error',
            'message': f'自动翻页超过上限 {MAX_LIST_FETCH_PAGES} 次，请缩小范围或联系维护'
        })
        return EXIT_BUSINESS_ERROR

    # 输出 Meta 与记录（群组列表无正式卡片类型，仅 JSONL）
    print_json_line({
        'record': 'meta',
        'status': 'success',
        'command': command_name,
        'totalCount': total if total is not None else len(all_rows),
        'pageSize': LIST_PAGE_SIZE_GROUP,
        'pages': pages_total,
        'isLastPage': True,
        'fetchPages': fetches,
        'endPage': last_page_num,
        'permissionTypeLegend': {str(k): v for k, v in PERMISSION_TYPE_LABELS.items()},
    })

    for idx, row in enumerate(all_rows, start=1):
        print_json_line({'record': 'groupCircle', 'index': idx, **row})

    return EXIT_OK


# -------------------------------------------------------------------------
# CLI 命令处理器
# -------------------------------------------------------------------------
def cmd_my_join_list(args: argparse.Namespace) -> int:
    verbose = False
    client = GroupCircleAPIClient(verbose=verbose)
    print_verbose_log(verbose, f'POST myJoinList host={HOST} 自动翻页')
    return process_paged_list('my_join_list', client.get_my_join_list, verbose)


def cmd_my_create_group_list(args: argparse.Namespace) -> int:
    verbose = False
    client = GroupCircleAPIClient(verbose=verbose)
    print_verbose_log(verbose, f'POST myCreateGroupList host={HOST} 自动翻页')
    return process_paged_list('my_create_group_list', client.get_my_create_group_list, verbose)


def _extract_task_ids(result_obj: Dict[str, Any]) -> List[str]:
    """从发布结果中提取任务 ID 列表。"""
    task_ids: List[str] = []
    # 直接从返回中取 taskId 字段
    tid = str(result_obj.get('taskId') or '').strip()
    if tid:
        task_ids.append(tid)
    # 也可能是 taskList
    tl = result_obj.get('taskList') or result_obj.get('taskIDList') or []
    if isinstance(tl, list):
        for item in tl:
            if isinstance(item, dict):
                t = str(item.get('taskId') or '').strip()
            else:
                t = str(item).strip()
            if t and t not in task_ids:
                task_ids.append(t)
    return task_ids


def _poll_task_status(
    client: GroupCircleAPIClient,
    task_ids: List[str],
    *,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """轮询任务状态，每 3 秒一次，直到全部完成或超时。"""
    for attempt in range(1, TASK_POLL_MAX_ATTEMPTS + 1):
        time.sleep(TASK_POLL_INTERVAL_SEC)
        try:
            body = client.query_multi_task_status(task_ids)
        except Exception as e:
            print_verbose_log(verbose, f'查询任务状态失败: {e}')
            continue

        if not is_api_success(body):
            print_verbose_log(verbose, f'查询任务状态接口返回失败: {body.get("message", "")}')
            continue

        task_list = (body.get('data') or {}).get('batchOprTaskList') or []
        print_verbose_log(
            verbose,
            f'[轮询 {attempt}/{TASK_POLL_MAX_ATTEMPTS}] 任务状态: '
            + ', '.join(f'{t.get("taskId","")}={t.get("taskStatus","")}' for t in task_list),
        )

        # 检查是否全部完成
        all_done = all(
            t.get('taskStatus') in (
                TASK_STATUS_SUCCESS,
                TASK_STATUS_FAILED,
                TASK_STATUS_PARTIAL,
                TASK_STATUS_CANCELLED,
            )
            for t in task_list
        )
        if all_done:
            return task_list

    # 超时：返回最后一轮的状态
    return task_list


def cmd_publish_circle(args: argparse.Namespace) -> int:
    verbose = False
    group_name = strip_group_name_markup(getattr(args, 'group_name', ''))
    if not group_name:
        return emit_input_error('group-name 不能为空，须传入当轮列表或搜索回执中的群组全称')
    try:
        content_ids, content_types, album_meta = resolve_publish_attachments(args)
    except ValueError as e:
        return emit_input_error(str(e))
    except RuntimeError as e:
        return emit_publish_error(str(e))

    dynamic_type_raw = getattr(args, 'dynamic_type', None)
    if dynamic_type_raw is not None and str(dynamic_type_raw).strip() != '':
        dynamic_type = str(dynamic_type_raw).strip()
        if dynamic_type not in PUBLISH_CIRCLE_DYNAMIC_TYPE_CHOICES:
            return emit_input_error('dynamic-type 仅支持 0(文件)、1(图片)、2(视频)')
    else:
        try:
            dynamic_type = infer_dynamic_type_for_publish(content_ids, content_types)
        except ValueError as e:
            return emit_input_error(str(e))
        except RuntimeError as e:
            return emit_publish_error(str(e))
    client = GroupCircleAPIClient(verbose=verbose)
    dynamic_asserts = [
        {'contentId': cid, 'contentType': ctype, 'sort': i + 1}
        for i, (cid, ctype) in enumerate(zip(content_ids, content_types))
    ]

    payload: Dict[str, Any] = {
        'groupId': str(args.group_id),
        'content': args.content,
        'dynamicAsserts': dynamic_asserts,
        'dynamicType': dynamic_type,
        'assetsNum': len(dynamic_asserts),
        'deviceId': client.device_id,
        'sponsorStatus': '0', # DEFAULT_SPONSOR_STATUS
    }
    if dynamic_type == PUBLISH_CIRCLE_DYNAMIC_TYPE_FILE:
        # 接口：文件类动态必传目标目录 id，0 表示根目录（无 CLI，固定根目录）
        payload['dstCatalogId'] = '0'

    print_verbose_log(verbose, 'POST publishCircle')
    
    # 实际调用分支
    try:
        body = client.publish_circle(payload)
    except RuntimeError as e:
        return emit_publish_error(str(e))
    except Exception as e:
        print_json_line({'record': 'error', 'status': 'error', 'message': str(e)})
        return EXIT_INTERNAL_ERROR

    if not is_api_success(body):
        return emit_publish_error(get_api_message(body), code=get_api_code(body))

    snapshot_trace_id()

    # 提取发布结果（异步任务提交成功，不代表实际执行成功）
    data = body.get('data')
    result_obj = dict(data) if isinstance(data, dict) else {'value': data}
    print_verbose_log(
        verbose,
        'publishCircle 提交回执: '
        + json.dumps({'record': 'result', 'command': 'publish_circle', **result_obj}, ensure_ascii=False),
    )

    # ---- 轮询任务状态 ----
    task_ids = _extract_task_ids(result_obj)
    final_tasks: List[Dict[str, Any]] = []
    if task_ids:
        print_verbose_log(verbose, f'开始轮询任务状态，taskIds={task_ids}')
        final_tasks = _poll_task_status(client, task_ids, verbose=verbose)
        # 给每个任务追加中文状态文本
        for t in final_tasks:
            t['taskStatusText'] = TASK_STATUS_TEXT.get(t.get('taskStatus'), '未知')
        print_verbose_log(
            verbose,
            '任务终态: '
            + json.dumps({'record': 'taskStatus', 'taskList': final_tasks}, ensure_ascii=False),
        )

    # 检查是否有任务失败
    failed_tasks = [
        t for t in final_tasks
        if t.get('taskStatus') in (TASK_STATUS_FAILED, TASK_STATUS_CANCELLED)
    ]
    if failed_tasks:
        remarks = [str(t.get('remark') or '').strip() for t in failed_tasks]
        remarks = [r for r in remarks if r]
        msg = '；'.join(remarks) if remarks else '任务执行失败'
        return emit_publish_error(msg)

    # 检查是否所有任务都成功完成（排除部分成功的情况）
    partial_tasks = [
        t for t in final_tasks
        if t.get('taskStatus') == TASK_STATUS_PARTIAL
    ]
    if partial_tasks:
        remarks = [str(t.get('remark') or '').strip() for t in partial_tasks]
        remarks = [r for r in remarks if r]
        msg = '；'.join(remarks) if remarks else '部分文件处理失败'
        return emit_publish_error(msg)

    # 仅在全部成功后输出 meta success
    success_meta: Dict[str, Any] = {
        'record': 'meta',
        'status': 'success',
        'command': 'publish_circle',
        'dynamicType': dynamic_type,
        'assetCount': len(content_ids),
        'renderCards': ['groupPath'],
    }
    if album_meta:
        success_meta.update(album_meta)
    print_json_line(success_meta)
    emit_group_path_card(group_id=str(args.group_id), group_name=group_name)

    return EXIT_OK


def cmd_search_group(args: argparse.Namespace) -> int:
    keywords = str(args.keywords or '').strip()
    if not keywords:
        return emit_input_error('keywords 不能为空')

    variants = search_keyword_variants(keywords)
    client = GroupCircleAPIClient(verbose=False)

    if len(variants) == 1:
        fetched = [fetch_search_group_pages(client, variants[0])]
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fetched = list(pool.map(lambda kw: fetch_search_group_pages(client, kw), variants))

    ok_results = [item for item in fetched if item.get('ok')]
    if not ok_results:
        first = fetched[0]
        print_json_line(first['error'])
        return int(first.get('exit_code') or EXIT_BUSINESS_ERROR)

    snapshot_trace_id()
    all_rows = merge_search_group_rows([item['rows'] for item in ok_results])
    fetches = sum(int(item.get('fetches') or 0) for item in fetched)
    last_ok = ok_results[-1]

    print_json_line({
        'record': 'meta',
        'status': 'success',
        'command': 'search_group',
        'keyword': keywords,
        'searchKeywords': variants,
        'totalCount': len(all_rows),
        'perPage': SEARCH_GROUP_PER_PAGE,
        'fetchPages': fetches,
        'endPageAfter': last_ok.get('page_after'),
        'permissionTypeLegend': {str(k): v for k, v in PERMISSION_TYPE_LABELS.items()},
    })
    for idx, row in enumerate(all_rows, start=1):
        print_json_line({'record': 'groupCircle', 'index': idx, **row})
    return EXIT_OK


# -------------------------------------------------------------------------
# CLI 入口与解析配置
# -------------------------------------------------------------------------
class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stdout)
        emit_input_error(message)
        print('提示：python3 cm_cloud_group_api.py <子命令> -h 查看该子命令参数。', file=sys.stdout, flush=True)
        self.exit(EXIT_INPUT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    epilog = """
示例:
  python3 cm_cloud_group_api.py my_join_list
  python3 cm_cloud_group_api.py search_group --keywords 女武神
  python3 cm_cloud_group_api.py publish_circle --group-id G1 --group-name 测试群 --content 你好 \\
    --fileid id1,id2
  python3 cm_cloud_group_api.py publish_circle --group-id G1 --group-name 测试群 --content 你好 \\
    --fileid id1,id2 --dynamic-type 1
  python3 cm_cloud_group_api.py publish_circle --group-id G1 --group-name 测试群 --content 你好 \\
    --fileid id1,id2 --dynamic-type 0 --file-type-list 1,2
  python3 cm_cloud_group_api.py publish_circle --group-id G1 --group-name 测试群 --content 你好 \\
    --album-id ALB1 --album-type album

退出码:
  0  成功（含列表为空）
  1  参数或用法错误
  2  业务失败（接口 success=false、code 非成功，或 HTTP 非 200）
  3  未预期内部错误

stdout 为 JSONL（每行一个 JSON）。成功时 `meta` 行含响应头 `trace_id`（首包快照）；接口失败时 `error` 可含 `trace_id` 与 `failedApi`。
发布成功额外追加 `:::groupPath` 卡片。

列表类子命令（my_join_list、my_create_group_list、search_group）会按接口分页自动拉取直至末页，
分页参数不对外暴露；脚本从第 1 页开始按内置 pageSize 自动拉取，再输出一行 meta（含 fetchPages 等）及全部条目。

群组列表每条 JSONL 的 record=groupCircle，含 permissionType 与 permissionTypeText；
meta 含 permissionTypeLegend：1 全权限、2 分享权限、3 查看、4 定制。
列表无正式 `:::` 卡片类型，禁止套用 fileList / imageList。
"""
    parser = CliArgumentParser(
        prog='cm_cloud_group_api.py',
        description='中国移动云盘群组 CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # 1. 我加入的群组
    cmd_join = subparsers.add_parser('my_join_list', help='查询我加入的群组')
    cmd_join.set_defaults(handler=cmd_my_join_list)

    # 2. 我创建的群组
    cmd_create = subparsers.add_parser('my_create_group_list', help='查询我创建的群组')
    cmd_create.set_defaults(handler=cmd_my_create_group_list)

    # 3. 搜索群组
    cmd_search = subparsers.add_parser('search_group', help='按关键词搜索群组')
    cmd_search.add_argument('--keywords', required=True, help='搜索关键字')
    cmd_search.set_defaults(handler=cmd_search_group)

    # 4. 发布群组动态
    cmd_pub = subparsers.add_parser('publish_circle', help='向群组发布动态')
    cmd_pub.add_argument('--group-id', required=True, help='群组 ID')
    cmd_pub.add_argument(
        '--group-name',
        required=True,
        help='群组全称，须来自当轮列表或搜索回执的 name',
    )
    cmd_pub.add_argument('--content', required=True, help='动态文字内容')
    cmd_pub.add_argument('--fileid', default='', help='云盘 fileId 列表，英文逗号分隔，最多 500 个；与 --album-id 二选一')
    cmd_pub.add_argument('--album-id', default='', help='相册 / 回忆故事 ID，脚本分页拉图后再发布；与 --fileid 二选一')
    cmd_pub.add_argument(
        '--album-type',
        default=None,
        choices=sorted(PUBLISH_ALBUM_TYPE_CHOICES),
        help='配合 --album-id：album=自定义相册，memory=回忆故事',
    )
    cmd_pub.add_argument(
        '--dynamic-type',
        required=False,
        default=None,
        choices=sorted(PUBLISH_CIRCLE_DYNAMIC_TYPE_CHOICES),
        help=(
            '发布类型：0=文件，1=图片，2=视频（与接口 dynamicType 一致）；'
            '省略则按 fileid 调云盘 batchGet：纯图→1，纯视频→2，否则→0（含混合、文件夹附件等）'
        ),
    )
    cmd_pub.add_argument('--file-type-list', default='', help='与 --fileid 同序、一一对应 dynamicAsserts.contentType：1=文件，2=文件夹；省略则每条按 1（文件）')
    cmd_pub.set_defaults(handler=cmd_publish_circle)

    subparsers.add_parser('help', help='显示根级帮助')

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    
    if args.command == 'help':
        parser.print_help()
        return EXIT_OK
        
    handler = getattr(args, 'handler', None)
    if not handler:
        parser.print_help()
        return EXIT_INPUT_ERROR

    clear_api_timings()
    start_cli_output_buffer()
    write_cli_output_line(format_runtime_env_line())
    try:
        return int(handler(args))
    finally:
        persist_flushed_stdout(flush_cli_output_buffer())


if __name__ == '__main__':
    sys.exit(main())