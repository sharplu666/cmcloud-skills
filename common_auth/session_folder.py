#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话文件夹接口封装。

调用 /richlifeApp/api/openclaw/session/folder/name 查询或生成会话默认文件夹，
供所有 skill 共用。服务端负责「查映射表 → 生成 folderName → 创建个人云文件夹」，
客户端只需一次调用拿到 (folderId, folderName)，再由调用方按需查询实际路径。
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# common/ 不在默认 sys.path；按 sibling 脚本惯例显式注入，使 mclaw.api 可导入。
_MCLAW_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'common')
)
if _MCLAW_ROOT not in sys.path:
    sys.path.insert(0, _MCLAW_ROOT)

from mclaw.api.operation.session_folder_name_api import (  # noqa: E402
    SessionFolderNameApi,
    SessionFolderNameRequest,
)
from mclaw.api.app_endpoint_map import resolve_url

try:
    from .cm_cloud_auth import X_YUN_CLIENT_INFO, get_skill_auth
    from mclaw.shared.cm_cloud.session_cli_validate import (
        normalize_cli_session_id,
        parse_cli_session_raw,
        parse_cron_job_id,
        resolve_cron_job_name,
        resolve_current_session,
        resolve_share_cron_job,
        validate_cli_session_raw,
    )
except ImportError:
    from cm_cloud_auth import X_YUN_CLIENT_INFO, get_skill_auth
    from mclaw.shared.cm_cloud.session_cli_validate import (
        normalize_cli_session_id,
        parse_cli_session_raw,
        parse_cron_job_id,
        resolve_cron_job_name,
        resolve_current_session,
        resolve_share_cron_job,
        validate_cli_session_raw,
    )


SESSION_FOLDER_NAME_PATH = '/richlifeApp/api/openclaw/session/folder/name'
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
SESSION_FOLDER_FALLBACK_HINT = '会话文件夹接口调用失败，已回退本地逐级创建目录'

# 云盘目录常量（与 cm_cloud_utils 保持一致，本模块自包含不依赖 cm_cloud_manage）
AI_SPACE_DIR_NAME = 'AI空间'
CHAT_FILE_DIR_NAME = '对话文件'
MY_TASK_DIR_NAME = '我的任务'


def _sub_dir_name_for_session(raw: str) -> str:
    """按 session 类型挑选 AI空间/<app_name> 下的二级目录名。

    cron（定时任务）与 share_cron（聚合型定时任务）→「我的任务」；
    其余（普通对话）→「对话文件」。
    """
    try:
        parsed = parse_cli_session_raw(str(raw or '').strip())
    except ValueError:
        return CHAT_FILE_DIR_NAME
    return MY_TASK_DIR_NAME if parsed.kind in ('cron', 'share_cron') else CHAT_FILE_DIR_NAME


# ---------------------------------------------------------------------------
# 纯路径工具（零外部依赖，复刻自 cm_cloud_common.py:174-211, 642-643）
# ---------------------------------------------------------------------------
def normalize_name_path(raw: Any) -> str:
    path = str(raw or "").strip()
    return path[5:] if path.startswith("root:") else path


def normalize_cloud_dir_path(raw: str) -> str:
    """规范化云盘目录路径，仅保留单个前导 /，去掉尾部 /，保留空格。"""
    raw = normalize_name_path(raw)
    text = str(raw or "").strip()
    if not text:
        return ""
    parts = [part for part in text.split("/") if part]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def compact_segment_name(name: str) -> str:
    """去掉段名中的全部空白，用于同级「带空格 / 不带空格」目录匹配。"""
    return "".join(ch for ch in str(name or "") if not ch.isspace())


def split_cloud_dir_path(raw: str) -> List[str]:
    """拆分云盘路径，保留各级目录名中的空格。"""
    path = normalize_name_path(str(raw or "").strip()).replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    path = path.strip()
    if path.startswith("/"):
        path = path[1:]
    if path.endswith("/"):
        path = path[:-1]
    return [part for part in path.split("/") if part != ""]


def join_cloud_dir_path(parts: List[str]) -> str:
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def is_folder_like_file_type(file_type: Any) -> bool:
    return str(file_type or "").strip().lower() == "folder"


def _verbose_log(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[verbose] {message}", file=sys.stdout, flush=True)


class SessionFolderError(RuntimeError):
    """会话文件夹接口异常。"""


def _parse_trace_str(trace_str: str) -> Dict[str, str]:
    """解析 trace_id 串（来自 mclaw.api 的 extract_trace_id，现为裸值）。

    兼容旧前缀格式 ``trace_id=xxx`` / ``x-yun-tid=yyy``；无前缀时视为 trace_id 裸值。
    """
    text = str(trace_str or '').strip()
    if not text:
        return {'trace_id': '', 'x_yun_tid': ''}
    if text.startswith('trace_id='):
        return {'trace_id': text[len('trace_id='):].strip(), 'x_yun_tid': ''}
    if text.startswith('x-yun-tid='):
        return {'trace_id': '', 'x_yun_tid': text[len('x-yun-tid='):].strip()}
    return {'trace_id': text, 'x_yun_tid': ''}


def _build_session_folder_record(
    *,
    status: str,
    request_url: str,
    request_payload: Optional[Dict[str, Any]],
    response_body: Any,
    trace_str: str = '',
    hint: str = '',
    folder_id: str = '',
    folder_name: str = '',
    folder_path: str = '',
) -> Dict[str, Any]:
    trace_ids = _parse_trace_str(trace_str)
    record: Dict[str, Any] = {
        'record': 'sessionFolder',
        'status': status,
        'requestUrl': request_url,
        'requestPayload': request_payload or {},
        'responseBody': response_body,
    }
    if hint:
        record['hint'] = hint
    if folder_id:
        record['folderId'] = folder_id
    if folder_name:
        record['folderName'] = folder_name
    if folder_path:
        record['folderPath'] = folder_path
    tid = trace_ids.get('trace_id')
    if tid:
        record['trace_id'] = str(tid).strip()
    ytid = trace_ids.get('x_yun_tid')
    if ytid:
        record['x-yun-tid'] = str(ytid).strip()
    return record


def _emit_session_folder_jsonl(record: Dict[str, Any]) -> None:
    """写入 stdout JSONL（缓冲开启时暂存）；无 CLI 缓冲时落到 stderr。"""
    line = json.dumps(record, ensure_ascii=False)
    try:
        from cli_timing import write_cli_output_line

        write_cli_output_line(line)
    except ImportError:
        print(line, file=sys.stdout, flush=True)


def _sync_session_folder_http_trace(trace_str: str = '') -> None:
    """同步 cli_trace 的 last_trace_id。

    旧路径用 ``set_last_trace_id(requests.Response)`` 同时写 trace_id / x-yun-tid 两个
    全局；新路径改走 ``capture_trace_string``（mclaw.api 调用方惯用），传入
    ``SessionFolderNameResponse.trace_id`` 前缀串。``trace_str`` 为空时清空。
    """
    try:
        from cli_trace import capture_trace_string, clear_last_trace_id, set_last_api_path

        set_last_api_path(SESSION_FOLDER_NAME_PATH)
        if trace_str:
            capture_trace_string(trace_str)
        else:
            clear_last_trace_id()
    except ImportError:
        pass


def _emit_session_folder_log(
    *,
    status: str,
    body: Any,
    trace_str: str = '',
    payload: Optional[Dict[str, Any]] = None,
    request_url: str = '',
    hint: str = '',
    folder_id: str = '',
    folder_name: str = '',
    folder_path: str = '',
) -> None:
    _sync_session_folder_http_trace(trace_str)
    _emit_session_folder_jsonl(
        _build_session_folder_record(
            status=status,
            request_url=request_url,
            request_payload=payload,
            response_body=body,
            trace_str=trace_str,
            hint=hint,
            folder_id=folder_id,
            folder_name=folder_name,
            folder_path=folder_path,
        )
    )


class SessionFolderClient:
    """会话文件夹接口客户端。

    构造时固定 openclawId / host / 重试策略；鉴权头每次请求实时读密文解密，
    支持多次调用 ``resolve`` 复用同一 client。
    """

    def __init__(
        self,
        *,
        openclaw_id: Optional[str] = None,
        host: Optional[str] = None,
        timeout: int = 30,
        retries: int = 2,
        retry_waits: Tuple[float, ...] = (1.0, 1.0),
    ) -> None:
        # 单模式（账号会话）下 OPENCLAW_ID 非必填：服务端不要求时留空即可。
        self._openclaw_id = (openclaw_id or os.getenv('OPENCLAW_ID') or '').strip()

        auth = get_skill_auth()
        self._host = (host or auth.host or '').rstrip('/')

        # 兜底路径用：app_name / MClaw 根来自 .env（非 token）；鉴权头每次请求实时解密
        self._app_name = auth.app_name
        self._mclaw_allowed_dir = f'/{AI_SPACE_DIR_NAME}/{self._app_name}'

        self._timeout = timeout
        self._retries = retries
        self._retry_waits = retry_waits
        self._last_failed_api_log: Optional[Dict[str, Any]] = None

    def _auth_headers(self) -> Dict[str, str]:
        """每次调用实时读会话文件产出鉴权头，无进程内 token 缓存。"""
        headers = get_skill_auth().get_common_header()
        headers['Content-Type'] = 'application/json'
        headers['x-yun-client-info'] = X_YUN_CLIENT_INFO
        return headers

    def resolve(
        self,
        session: str,
        *,
        log_on_error: bool = True,
        enable_auto_create_dir: bool = True,
    ) -> Tuple[str, str, str]:
        """查询/生成会话默认文件夹，返回 (folderId, folderName, namePath)。

        namePath 为服务端返回的文件全路径（分隔符 "/"）；后台未上线时可能为空，
        由调用方兜底拼接。

        ``enable_auto_create_dir`` 透传为接口入参 ``enableAutoCreateDir``：
          - ``True``（默认）：服务端返回目录名的同时创建目录，folderId 非空；
          - ``False``：只返回目录名/路径、不创建目录，folderId 为空串。

        流程：
          1. 解析 session → (kind, body)，区分 chat / cron；
             cron 场景从 jobs.json 查 jobName
          2. 调用 /session/folder/name 接口
          3. HTTP 不通（网络异常 / 5xx）最多重试 3 次，每次间隔 1s
          4. 业务异常（code != '0000'，或 enable_auto_create_dir=True 时 folderId 空）
             打印错误 + 响应体 + trace_id 后抛 SessionFolderError
        """
        raw = str(session or '').strip()
        try:
            parsed = parse_cli_session_raw(raw)
        except ValueError as exc:
            raise SessionFolderError(str(exc)) from exc

        if parsed.kind == 'cron':
            session_type = 'cron'
            # 兼容后台通过回调接口获取的sessionId
            session_id_for_api = raw
            job_name = resolve_cron_job_name(parse_cron_job_id(parsed.body)) or '定时任务'
        elif parsed.kind == 'share_cron':
            # 聚合型定时任务：真正的 jobId 由 jobs.json 的 sessionTarget 反查，
            # 直接作为 sessionId 发给服务端关联任务
            session_type = 'cron'
            job_id, job_name = resolve_share_cron_job(parsed.body)
            session_id_for_api = job_id
            job_name = job_name or '定时任务'
        else:
            session_type = 'chat'
            session_id_for_api = parsed.body
            job_name = None

        payload: Dict[str, Any] = {
            'sessionId': session_id_for_api,
            'sessionType': session_type,
            'openclawId': self._openclaw_id,
        }
        if session_type == 'cron':
            payload['jobName'] = job_name

        return self._post_and_validate(
            payload, log_on_error=log_on_error, enable_auto_create_dir=enable_auto_create_dir
        )

    def _remember_failed_api_log(
        self,
        *,
        body: Any,
        trace_str: str = '',
        payload: Dict[str, Any],
        request_url: str,
    ) -> None:
        self._last_failed_api_log = {
            'body': body,
            'trace_str': trace_str,
            'payload': payload,
            'request_url': request_url,
        }

    def _log_or_remember_api_failure(
        self,
        *,
        log_on_error: bool,
        body: Any,
        trace_str: str = '',
        payload: Dict[str, Any],
        request_url: str,
    ) -> None:
        if log_on_error:
            _emit_session_folder_log(
                status='error',
                body=body,
                trace_str=trace_str,
                payload=payload,
                request_url=request_url,
            )
        else:
            self._remember_failed_api_log(
                body=body,
                trace_str=trace_str,
                payload=payload,
                request_url=request_url,
            )

    def _post_and_validate(
        self,
        payload: Dict[str, Any],
        *,
        log_on_error: bool = True,
        enable_auto_create_dir: bool = True,
    ) -> Tuple[str, str, str]:
        """走 mclaw.api ``SessionFolderNameApi`` 发起请求并做业务校验。

        失败时输出 sessionFolder JSONL 后抛 ``SessionFolderError``。
        返回 (folderId, folderName, namePath)；namePath 为后台返回的全路径，
        未上线/未返回时为空串，由上层兜底拼接。

        ``enable_auto_create_dir`` 透传为 ``enableAutoCreateDir``：``False`` 时只返回
        目录名不创建目录，folderId 允许为空（此时仅校验 code=='0000'）。

        重试 / 超时 / 鉴权头刷新 / trace_id 提取 / timing 由 mclaw.api 基类
        （``BaseSyncApi.execute`` → ``post_json_with_retry``）统一处理；本方法只负责
        构造请求、按业务结果发 JSONL / 抛错。
        """
        url = resolve_url(self._host, SESSION_FOLDER_NAME_PATH)

        req = SessionFolderNameRequest(
            sessionId=payload['sessionId'],
            openclawId=payload['openclawId'],
            sessionType=payload.get('sessionType', 'chat'),
            jobName=payload.get('jobName'),  # None → to_payload 自动剔除
            enableAutoCreateDir=enable_auto_create_dir,
        )
        api = SessionFolderNameApi(
            host=self._host, auth_fn=self._auth_headers,
        )

        try:
            response = api.execute(
                req,
                timeout=self._timeout,
                max_retries=self._retries,
                retry_delay=self._retry_waits[0] if self._retry_waits else 1.0,
            )
        except Exception as exc:  # post_json_with_retry 耗尽后抛 RuntimeError
            self._log_or_remember_api_failure(
                log_on_error=log_on_error,
                body=f'HTTP 异常：{exc}',
                trace_str='',
                payload=payload,
                request_url=url,
            )
            raise SessionFolderError(
                f'请求失败：{SESSION_FOLDER_NAME_PATH} 网络异常：{exc}'
            ) from exc

        folder_id = str(response.folder_id or '').strip()
        folder_name = str(response.folder_name or '').strip()
        name_path = str(response.name_path or '').strip()
        trace_str = str(getattr(response, 'trace_id', '') or '')

        # enable_auto_create_dir=False 时只拿目录名、不创建，folderId 允许为空；
        # 仅在创建场景（默认）下把空 folderId 视为业务失败 / 降级。
        require_folder_id = enable_auto_create_dir
        if response.code != '0000' or (require_folder_id and not folder_id):
            # 业务失败 / 降级（folderId 为空时服务端按原始 sessionId 降级返回）
            self._log_or_remember_api_failure(
                log_on_error=log_on_error,
                body=response.raw,
                trace_str=trace_str,
                payload=payload,
                request_url=url,
            )
            raise SessionFolderError(
                f'会话文件夹接口返回异常：code={response.code!r} folderId={folder_id!r}'
            )

        self._last_failed_api_log = None
        return folder_id, folder_name, name_path

    def _retry_wait(self, attempt: int) -> float:
        if attempt < len(self._retry_waits):
            return self._retry_waits[attempt]
        return 0.0

    # ------------------------------------------------------------------
    # 自包含云盘 HTTP 调用（用于 ensure_default_folder 兜底链）
    # ------------------------------------------------------------------
    def _post_cloud_json(
        self,
        path: str,
        payload: Dict[str, Any],
        *,
        retries: int = 1,
        retry_waits: Tuple[float, ...] = (1.0, 1.0),
    ) -> Dict[str, Any]:
        """统一云盘 POST JSON 调用，含 5xx/429 重试。失败抛 SessionFolderError。"""
        url = resolve_url(self._host, path)
        max_attempts = retries + 1
        resp: Optional[requests.Response] = None

        for attempt in range(max_attempts):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=self._auth_headers(),
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if attempt < max_attempts - 1:
                    time.sleep(retry_waits[attempt] if attempt < len(retry_waits) else 0)
                    continue
                raise SessionFolderError(
                    f'请求失败：{path} 网络异常：{exc}'
                ) from exc

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise SessionFolderError(
                        f'请求失败：{path} 响应非 JSON'
                    ) from exc

            if resp.status_code in _RETRYABLE_HTTP_STATUS and attempt < max_attempts - 1:
                time.sleep(retry_waits[attempt] if attempt < len(retry_waits) else 0)
                continue

            raise SessionFolderError(
                f'请求失败：{path} HTTP {resp.status_code}: {resp.text}'
            )

        raise SessionFolderError(f'请求失败：{path} 达到重试上限')

    def _cloud_check_exists(self, parent_file_id: str, file_name: str) -> Dict[str, Any]:
        """单条 batchCheckExists，返回标准化 {exist, appFileId, fileType}。"""
        result = self._post_cloud_json(
            '/richlifeApp/personalSaas/file/batchCheckExists',
            {
                'subRequestList': [
                    {'id': '0', 'body': {'parentFileId': parent_file_id, 'fileName': file_name}}
                ]
            },
        )
        if not (result.get('success') and str(result.get('code') or '').strip() == '0000'):
            raise SessionFolderError(
                f'checkExists 失败：{result.get("message") or result.get("code") or "未知错误"}'
            )
        sub_list = (result.get('data') or {}).get('subResponseList') or []
        if not sub_list:
            raise SessionFolderError(
                f'checkExists 失败：未返回子响应 (parent={parent_file_id!r}, name={file_name!r})'
            )
        row = sub_list[0] if isinstance(sub_list[0], dict) else {}
        if str(row.get('code') or '').strip() != '0000':
            raise SessionFolderError(
                f'checkExists 失败：{row.get("message") or row.get("code") or "未知错误"}'
            )
        data = row.get('data') or {}
        return {
            'exist': bool(data.get('exist')),
            'appFileId': str(data.get('fileId') or data.get('appFileId') or '').strip(),
            'fileType': str(data.get('type') or data.get('fileType') or '').strip().lower(),
        }

    def _cloud_create_folder(self, name: str, parent_file_id: str = '/') -> Dict[str, Any]:
        """createFolder，返回 data dict（含 fileId/fileName/parentFileId）。"""
        result = self._post_cloud_json(
            '/richlifeApp/personalSaas/file/createFolder',
            {
                'name': name,
                'parentFileId': parent_file_id,
                'type': 'folder',
                'fileRenameMode': 'refuse',
            },
        )
        if not (result.get('success') and result.get('code') == '0000'):
            raise SessionFolderError(
                f'创建文件夹失败：{result.get("message") or result.get("code")}; '
                f'name={name}, parentFileId={parent_file_id}'
            )
        return result.get('data') or {}

    # ------------------------------------------------------------------
    # 目录操作（用于 ensure_default_folder 兜底链）
    # ------------------------------------------------------------------
    def _reuse_existing_folder(
        self,
        parent_id: str,
        folder_name: str,
        existing: Dict[str, Any],
        *,
        verbose: bool,
        matched_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing_file_id = str(existing.get("appFileId") or "").strip()
        if not existing_file_id:
            raise SessionFolderError(f"复用目录失败：{folder_name} 已存在但未返回 appFileId")
        file_type = str(existing.get("fileType") or "").strip().lower()
        if not file_type:
            raise SessionFolderError(f"复用目录失败：{folder_name} 已存在但未返回 fileType")
        if not is_folder_like_file_type(file_type):
            raise SessionFolderError(
                f"复用目录失败：父目录 {parent_id} 下已存在同名对象 {folder_name}，"
                f"但其类型为 {file_type!r} 而不是文件夹，无法复用为目录"
            )
        label = matched_name or folder_name
        _verbose_log(verbose, f"reuse folder: {label} -> {existing_file_id}")
        return {"fileId": existing_file_id, "parentFileId": parent_id}

    def _ensure_folder(
        self,
        parent_id: str,
        folder_name: str,
        *,
        verbose: bool = False,
    ) -> Dict[str, Any]:
        existing = self._cloud_check_exists(parent_id, folder_name)
        if existing.get("exist"):
            return self._reuse_existing_folder(parent_id, folder_name, existing, verbose=verbose)

        if any(ch.isspace() for ch in folder_name):
            compact_name = compact_segment_name(folder_name)
            if compact_name and compact_name != folder_name:
                alt = self._cloud_check_exists(parent_id, compact_name)
                if alt.get("exist"):
                    _verbose_log(
                        verbose,
                        f"folder name {folder_name!r}: reuse no-space sibling {compact_name!r}",
                    )
                    return self._reuse_existing_folder(
                        parent_id,
                        folder_name,
                        alt,
                        verbose=verbose,
                        matched_name=compact_name,
                    )

        _verbose_log(verbose, f"create folder: {folder_name} under {parent_id}")
        return self._cloud_create_folder(folder_name, parent_id)

    def _ensure_folder_path_parts(
        self,
        parts: List[str],
        *,
        start_parent_file_id: str = "/",
        verbose: bool = False,
    ) -> Dict[str, Any]:
        if not parts:
            raise SessionFolderError("目录路径不能为空")
        parent_id = str(start_parent_file_id or "/").strip() or "/"
        folder: Dict[str, Any] = {"fileId": parent_id, "parentFileId": ""}
        for part in parts:
            folder = self._ensure_folder(parent_id, part, verbose=verbose)
            parent_id = str(folder.get("fileId") or "").strip()
            if not parent_id:
                raise SessionFolderError(f"创建目录失败：{part!r} 未返回 fileId")
        return folder

    def _resolve_ai_space_folder_id(self, *, verbose: bool = False) -> str:
        """定位根目录下已存在的「AI空间」文件夹 fileId（不创建 AI空间）。"""
        existing = self._cloud_check_exists("/", AI_SPACE_DIR_NAME)
        if not existing.get("exist"):
            raise SessionFolderError(
                f'操作失败：个人云根目录下未找到「{AI_SPACE_DIR_NAME}」，请确认云盘环境'
            )
        file_id = str(existing.get("appFileId") or "").strip()
        if not file_id:
            raise SessionFolderError(f'操作失败：「{AI_SPACE_DIR_NAME}」已存在但未返回 fileId')
        file_type = str(existing.get("fileType") or "").strip().lower()
        if not is_folder_like_file_type(file_type):
            raise SessionFolderError(
                f'操作失败：「{AI_SPACE_DIR_NAME}」存在但不是文件夹（type={file_type!r}）'
            )
        _verbose_log(verbose, f"resolve_ai_space_folder_id -> {file_id!r}")
        return file_id

    # ------------------------------------------------------------------
    # 主入口：查询/生成默认会话目录，返回 (folderId, 完整路径)
    # ------------------------------------------------------------------
    def ensure_default_folder(
        self,
        session: str,
        *,
        verbose: bool = False,
        error_cls: type[Exception] = SessionFolderError,
        create: bool = True,
    ) -> Tuple[str, str]:
        """查询/生成默认会话目录，返回 (目录 fileId, 完整路径)。

        ``create=True``（默认）：服务端 /session/folder/name 接口（enableAutoCreateDir=true）
        创建目录并返回 fileId；路径优先用返回的 namePath，未返回时由常量 + folderName 本地拼接；
        接口失败时回退到本地逐级创建，保证可用性。

        ``create=False``（只查询不创建）：传 enableAutoCreateDir=false，只返回目录名/路径、
        folderId 为空串；**不做本地创建兜底**，接口失败直接抛错。
        """
        raw = str(session or "").strip()
        validate_cli_session_raw(raw, error_cls=error_cls)
        sub_dir_name = _sub_dir_name_for_session(raw)

        # 账号会话模式：APK 无 openclaw 会话目录接口，直接本地逐级 ensure（checkExists + create）。
        if not create:
            return '', join_cloud_dir_path([AI_SPACE_DIR_NAME, self._app_name, sub_dir_name, ''])
        file_id, folder_path = self._ensure_default_folder_via_local(
            raw, verbose=verbose, error_cls=error_cls, sub_dir_name=sub_dir_name
        )
        _verbose_log(
            verbose,
            f"ensure_default_folder(local) -> fileId={file_id!r} path={folder_path!r}",
        )
        return file_id, folder_path

    def _ensure_default_folder_via_local(
        self,
        raw_session: str,
        *,
        verbose: bool = False,
        error_cls: type[Exception] = SessionFolderError,
        sub_dir_name: str = CHAT_FILE_DIR_NAME,
    ) -> Tuple[str, str]:
        """本地兜底：逐级创建 /AI空间/<APP_NAME>/<sub_dir_name>/{session}。"""
        normalized_session_id = normalize_cli_session_id(raw_session, error_cls=error_cls)
        if not normalized_session_id:
            raise error_cls(
                "上传失败：Session 无效或为空。"
            )
        ai_space_id = self._resolve_ai_space_folder_id(verbose=verbose)
        folder = self._ensure_folder_path_parts(
            [self._app_name, sub_dir_name, normalized_session_id],
            start_parent_file_id=ai_space_id,
            verbose=verbose,
        )
        file_id = str(folder.get("fileId") or "").strip()
        if not file_id:
            raise error_cls("上传失败：默认会话目录创建成功但未返回 fileId")
        full_path = join_cloud_dir_path(
            [AI_SPACE_DIR_NAME, self._app_name, sub_dir_name, normalized_session_id]
        )
        return file_id, full_path

    def ensure_task_named_folder(
        self,
        session: str,
        folder_name: str,
        *,
        verbose: bool = False,
        error_cls: type[Exception] = SessionFolderError,
    ) -> Tuple[str, str]:
        """在会话子目录（对话文件/我的任务）下 ensure 指定名称的目录，返回 (fileId, 完整路径)。

        与 :meth:`ensure_default_folder` 的差异：叶子目录名由调用方指定（如按 query 命名），
        直接挂在 ``/AI空间/<APP_NAME>/<对话文件|我的任务>/`` 下，不经过服务端按会话生成的
        一级目录（服务端目录名与会话内容相关，容易与 query 目录名重复或产生误导）。

        全程本地逐级 ensure（check_exists 复用 / createFolder 创建），不调用服务端
        /session/folder/name 建目录接口。
        """
        raw = str(session or "").strip()
        validate_cli_session_raw(raw, error_cls=error_cls)
        name = str(folder_name or "").strip()
        if not name:
            raise error_cls("目录名不能为空")
        sub_dir_name = _sub_dir_name_for_session(raw)

        ai_space_id = self._resolve_ai_space_folder_id(verbose=verbose)
        parent = self._ensure_folder_path_parts(
            [self._app_name, sub_dir_name],
            start_parent_file_id=ai_space_id,
            verbose=verbose,
        )
        parent_id = str(parent.get("fileId") or "").strip()
        if not parent_id:
            raise error_cls(f"创建目录失败：{sub_dir_name!r} 未返回 fileId")
        folder = self._ensure_folder(parent_id, name, verbose=verbose)
        file_id = str(folder.get("fileId") or "").strip()
        if not file_id:
            raise error_cls(f"创建目录失败：{name!r} 未返回 fileId")
        full_path = join_cloud_dir_path(
            [AI_SPACE_DIR_NAME, self._app_name, sub_dir_name, name]
        )
        _verbose_log(verbose, f"ensure_task_named_folder -> fileId={file_id!r} path={full_path!r}")
        return file_id, full_path


def get_session_folder(session: str, **client_kwargs: Any) -> Tuple[str, str, str]:
    """便捷入口：用默认配置创建客户端并解析 session。

    返回 (folderId, folderName, namePath)；namePath 可能为空。
    """
    return SessionFolderClient(**client_kwargs).resolve(session)


def ensure_default_session_upload_parent(
    session: str,
    *,
    verbose: bool = False,
    error_cls: type[Exception] = SessionFolderError,
) -> Tuple[str, str]:
    """便捷入口：等价于 SessionFolderClient().ensure_default_folder(session, ...)。

    全程由服务端 /session/folder/name 接口处理，
    返回 (folderId, full_path)。
    """
    return SessionFolderClient().ensure_default_folder(
        session, verbose=verbose, error_cls=error_cls
    )


def query_default_session_folder(
    session: str,
    *,
    verbose: bool = False,
    error_cls: type[Exception] = SessionFolderError,
) -> Tuple[str, str]:
    """便捷入口：只查询不创建默认会话目录（enableAutoCreateDir=false）。

    等价于 ``SessionFolderClient().ensure_default_folder(session, create=False, ...)``。
    返回 (folderId, full_path)；不创建目录时 folderId 为空串、full_path 来自服务端
    namePath（或本地按规则拼接）。与 ``ensure_default_session_upload_parent``（创建路径）成对。
    """
    return SessionFolderClient().ensure_default_folder(
        session, verbose=verbose, error_cls=error_cls, create=False
    )


def ensure_task_named_session_folder(
    session: str,
    folder_name: str,
    *,
    verbose: bool = False,
    error_cls: type[Exception] = SessionFolderError,
) -> Tuple[str, str]:
    """便捷入口：等价于 SessionFolderClient().ensure_task_named_folder(session, folder_name, ...)。

    在 /AI空间/<APP_NAME>/<对话文件|我的任务>/ 下 ensure 指定名称的目录（如按 query 命名），
    返回 (folderId, full_path)。
    """
    return SessionFolderClient().ensure_task_named_folder(
        session, folder_name, verbose=verbose, error_cls=error_cls
    )
