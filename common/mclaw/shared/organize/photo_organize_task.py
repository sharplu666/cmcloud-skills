#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""photoOrganize 任务生命周期：submit / query / retry + plan rows → 服务端行转换。

跨 skill 复用：任何调 photoOrganize（归档/相册/回忆故事）三接口的整理流程，都可用
``OrganizeTaskClient`` 统一调度，避免各技能各自重写一遍「请求构造 + 业务码判定 + 已成功无需
重试 + 回执数据结构」。

设计戒律：
  - **经封装好的 API，不直接 requests**：调 ``dispatcher.operation.submit_photo_organize_task``
    等（在 ``mclaw.api.operation.*``，含鉴权/重试/trace/超时/multipart 封装），与
    ``shared.cm_cloud.folder_ops`` 调 ``dispatcher.personal_saas.create_folder`` 同性质。
    ``dispatcher`` 默认 ``mclaw.shared.cm_cloud.cloud_dispatcher.get_cloud_dispatcher()``。
    禁止在 shared 层拿 ``requests`` 拼 URL 自己发——会绕过 trace/计时/重试/落盘。
  - **类内做业务码判定与 skipped 语义**：``success && code=='0000'`` 判定、``10030814``
    （任务已成功无需重试）→ ``skipped`` 收进类内，调用方只看返回结构，不重复判码。
  - **回执只给数据结构，不碰 stdout 格式**：``TaskSnapshot`` / ``SubmitResult`` / ``RetryResult``
    是纯数据，record 命名 / sayToUser 文案 / 确认纪律留技能层（各技能回执约定不同）。
  - **to_server_rows 是纯函数**：plan rows → 服务端 jsonl 行，无 HTTP、无副作用，便于单测。

plan.jsonl 行格式（与 ``OrganizeSession`` 约定）：
  - header 行：``{"record":"header","planHash":...,"organizeType":"file","name":...,...}``
  - row 行：``{"record":"row","fileId":...,"bucket":...,"name":...,"index":N,
    "targetPath":...,"targetFileName"?}``（drive）；album/memory 用 ``targetName`` 代替 targetPath。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mclaw.api.operation.photo_organize_query_api import (
    PhotoOrganizeQueryRequest,
    PhotoOrganizeQueryResponse,
)
from mclaw.api.operation.photo_organize_retry_api import (
    PhotoOrganizeRetryRequest,
    PhotoOrganizeRetryResponse,
)
from mclaw.api.operation.photo_organize_submit_api import (
    PHOTO_ORGANIZE_FILE_MAX_BYTES,
    PhotoOrganizeSubmitRequest,
    PhotoOrganizeSubmitResponse,
)
from mclaw.shared.cm_cloud.cloud_dispatcher import get_cloud_dispatcher
from mclaw.shared.postprocess.api_obs import err_message

__all__ = [
    'OrganizeTaskClient',
    'to_server_rows',
    'TaskSnapshot',
    'SubmitResult',
    'RetryResult',
    'OrganizeTaskError',
    'TASK_TYPE_DRIVE',
    'TASK_TYPE_ALBUM',
    'TASK_TYPE_MEMORY',
    'TASK_STATUS_TEXT',
    'CODE_ALREADY_SUCCESS',
]

# 任务类型：1 归档(drive) / 2 相册(album) / 3 回忆故事(memory)
TASK_TYPE_DRIVE = 1
TASK_TYPE_ALBUM = 2
TASK_TYPE_MEMORY = 3

# 任务状态：1 待处理 / 2 处理中 / 3 全部成功 / 4 全部失败 / 5 部分成功
TASK_STATUS_TEXT = {
    1: '待处理',
    2: '处理中',
    3: '全部成功',
    4: '全部失败',
    5: '部分成功',
}

#: 服务端码：任务已成功，无需重试（retry 时按 skipped 处理）
CODE_ALREADY_SUCCESS = '10030814'

#: album/memory 行允许透传的可选字段（回忆故事筛选用）
_ALBUM_OPTIONAL = (
    'contentHash',
    'contentHashAlgorithm',
    'imgQuality',
    'takenAt',
    'thingLabels',
)


class OrganizeTaskError(Exception):
    """任务接口调用失败（网络异常或业务失败）。``code`` 为服务端码（若有）。"""

    def __init__(self, message: str, *, code: str = '', trace_id: str = '') -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.trace_id = trace_id


# ──────────────────────────── 纯函数：plan rows → 服务端行 ────────────────────────────


def to_server_rows(task_type: int, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """plan rows → 服务端 jsonl 行。

    - ``task_type=1``（drive）：``{fileId, targetPath, targetFileName?}``；``targetPath`` 必填。
    - ``task_type=2/3``（album/memory）：``{fileId, targetName, <可选字段>}``；``targetName``
      取 ``targetPath``（册名/故事名），无则取 ``group``。
    缺 fileId / 目标为空 → ``ValueError``。
    """
    if task_type not in (TASK_TYPE_DRIVE, TASK_TYPE_ALBUM, TASK_TYPE_MEMORY):
        raise ValueError(
            f'task_type 仅支持 1 drive / 2 album / 3 memory，收到 {task_type!r}'
        )
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        file_id = str(row.get('fileId') or row.get('file_id') or '').strip()
        if not file_id:
            raise ValueError(f'规划第 {idx} 行缺少 fileId: {row}')
        if task_type == TASK_TYPE_DRIVE:
            target_path = str(row.get('targetPath') or row.get('target_path') or '').strip()
            if not target_path:
                raise ValueError(
                    f'规划第 {idx} 行缺少 targetPath（drive 必填）: fileId={file_id}'
                )
            item: Dict[str, Any] = {'fileId': file_id, 'targetPath': target_path}
            name = str(row.get('targetFileName') or row.get('target_name') or '').strip()
            if name:
                item['targetFileName'] = name
        else:
            target_name = (
                str(row.get('targetPath') or '').strip()
                or str(row.get('targetName') or '').strip()
                or str(row.get('group') or '').strip()
            )
            if not target_name:
                raise ValueError(
                    f'规划第 {idx} 行缺少 targetPath/targetName/group（相册或回忆名）: fileId={file_id}'
                )
            item = {'fileId': file_id, 'targetName': target_name}
            for key in _ALBUM_OPTIONAL:
                val = row.get(key)
                if val not in (None, '', []):
                    item[key] = val
        out.append(item)
    return out


# ──────────────────────────── 回执数据结构 ────────────────────────────


@dataclass(frozen=True)
class TaskSnapshot:
    """任务状态快照（query / retry 共用）。"""

    task_id: str
    status: int                           # 1-5
    status_text: str                      # 中文
    is_terminal: bool                     # status ∈ {3,4,5}
    is_success: bool                      # status == 3
    task_type: int = 0
    total_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    error_code: str = ''
    error_msg: str = ''
    processing_hint: str = ''
    finish_content: str = ''
    results: List[Any] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_receipt_dict(self) -> Dict[str, Any]:
        """转回执用 dict（camelCase，None 安全）。供各技能 services 统一序列化，避免重复。"""
        return {
            'status': self.status,
            'statusText': self.status_text,
            'isTerminal': self.is_terminal,
            'isSuccess': self.is_success,
            'taskType': self.task_type,
            'totalCount': self.total_count,
            'successCount': self.success_count,
            'failCount': self.fail_count,
            'errorCode': self.error_code,
            'errorMsg': self.error_msg,
            'processingHint': self.processing_hint,
            'finishContent': self.finish_content,
        }


@dataclass(frozen=True)
class SubmitResult:
    """submit 回执：``task_id`` 必有；``task_info`` 仅同步终态时非 None。
    ``results`` 为接口原生 ``data.results``（同步终态时可能含创建的目标目录/相册/故事明细），
    透传给技能层自行渲染——公共库不做卡片渲染（属技能业务逻辑）。
    """

    task_id: str
    task_info: Optional[TaskSnapshot] = None
    row_count: int = 0
    results: List[Any] = field(default_factory=list)


@dataclass(frozen=True)
class RetryResult:
    """retry 回执。``skipped`` 为 True 表示任务已成功无需重试（按好消息处理）。"""

    task_id: str
    skipped: bool = False
    task_info: Optional[TaskSnapshot] = None


# ──────────────────────────── 响应 → 快照 ────────────────────────────


def _snapshot_from_query(resp: PhotoOrganizeQueryResponse, task_id: str) -> TaskSnapshot:
    info = resp.task_info
    if info is None:
        return TaskSnapshot(
            task_id=task_id,
            status=0,
            status_text='未知',
            is_terminal=False,
            is_success=False,
            results=list(resp.results or []),
            raw=resp.raw if hasattr(resp, 'raw') else {},
        )
    return TaskSnapshot(
        task_id=str(info.task_id or task_id),
        status=int(info.status or 0),
        status_text=TASK_STATUS_TEXT.get(int(info.status or 0), '未知'),
        is_terminal=bool(info.is_terminal),
        is_success=bool(info.is_success),
        task_type=int(info.task_type or 0),
        total_count=int(info.total_count or 0),
        success_count=int(info.success_count or 0),
        fail_count=int(info.fail_count or 0),
        error_code=str(info.error_code or ''),
        error_msg=str(info.error_msg or ''),
        processing_hint=str(info.processing_hint or ''),
        finish_content=str(info.finish_content or ''),
        results=list(resp.results or []),
        raw=resp.raw if hasattr(resp, 'raw') else {},
    )


def _snapshot_from_retry(resp: PhotoOrganizeRetryResponse, task_id: str) -> TaskSnapshot:
    info = resp.task_info
    if info is None:
        return TaskSnapshot(
            task_id=task_id,
            status=0,
            status_text='未知',
            is_terminal=False,
            is_success=False,
            results=list(resp.results or []),
            raw=resp.raw if hasattr(resp, 'raw') else {},
        )
    return TaskSnapshot(
        task_id=str(info.task_id or task_id),
        status=int(info.status or 0),
        status_text=TASK_STATUS_TEXT.get(int(info.status or 0), '未知'),
        is_terminal=bool(info.is_terminal),
        is_success=bool(info.is_success),
        task_type=int(info.task_type or 0),
        total_count=int(info.total_count or 0),
        success_count=int(info.success_count or 0),
        fail_count=int(info.fail_count or 0),
        error_code=str(info.error_code or ''),
        error_msg=str(info.error_msg or ''),
        processing_hint=str(info.processing_hint or ''),
        finish_content=str(info.finish_content or ''),
        results=list(resp.results or []),
        raw=resp.raw if hasattr(resp, 'raw') else {},
    )


def _check_business(resp: Any, action: str) -> None:
    """统一业务码判定：非 ``success && code=='0000'`` 抛 ``OrganizeTaskError``。"""
    ok = bool(getattr(resp, 'success', False)) and str(getattr(resp, 'code', '') or '') == '0000'
    if not ok:
        raise OrganizeTaskError(
            f'{action}业务失败：{err_message(resp, "业务失败")}',
            code=str(getattr(resp, 'code', '') or ''),
            trace_id=str(getattr(resp, 'trace_id', '') or ''),
        )


# ──────────────────────────── 客户端 ────────────────────────────


class OrganizeTaskClient:
    """photoOrganize 任务生命周期：submit / query / retry。

    经 ``dispatcher.operation.*`` 调封装好的 API（含鉴权/重试/trace/multipart）。
    ``dispatcher`` 默认进程单例 ``get_cloud_dispatcher()``；测试可注入假的。
    """

    def __init__(self, dispatcher: Any = None) -> None:
        self._dispatcher = dispatcher

    @property
    def dispatcher(self) -> Any:
        if self._dispatcher is None:
            self._dispatcher = get_cloud_dispatcher()
        return self._dispatcher

    def submit(
        self,
        *,
        rows: List[Dict[str, Any]],
        task_type: int = TASK_TYPE_DRIVE,
        session_id: str,
        processing_hint: Optional[str] = None,
        file_name: str = 'file_plan.jsonl',
    ) -> SubmitResult:
        """提交整理任务（multipart 上传 plan 的服务端行 JSONL）。

        - ``rows``：plan rows（``OrganizeSession.read_plan()[1]`` 或等价结构）。
        - 返回 ``SubmitResult``：``task_id`` 必有；小任务同步终态时 ``task_info`` 非 None。
        - 网络/业务失败抛 ``OrganizeTaskError``。
        """
        server_rows = to_server_rows(task_type, rows)
        content = (
            ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in server_rows)
        ).encode('utf-8')
        if len(content) > PHOTO_ORGANIZE_FILE_MAX_BYTES:
            raise OrganizeTaskError(
                f'规划文件超过 {PHOTO_ORGANIZE_FILE_MAX_BYTES // (1024 * 1024)}MB 上限'
                f'（{len(content)} 字节）'
            )
        request = PhotoOrganizeSubmitRequest(
            type_=task_type,
            session_id=session_id,
            file_name=file_name,
            file_content=content,
            process_hint=processing_hint or None,
        )
        try:
            resp: PhotoOrganizeSubmitResponse = (
                self.dispatcher.operation.submit_photo_organize_task(request)
            )
        except OrganizeTaskError:
            raise
        except Exception as exc:  # RuntimeError 等
            raise OrganizeTaskError(
                f'提交整理任务失败：{exc}；请停止并交用户决策，勿自动重试'
            ) from exc
        _check_business(resp, '提交整理任务')
        task_id = str(resp.task_id or '').strip()
        if not task_id:
            raise OrganizeTaskError('提交整理任务失败：服务端未返回 taskId')
        task_info: Optional[TaskSnapshot] = None
        if resp.task_info is not None:
            task_info = _snapshot_from_query(
                _coerce_query_resp(resp), task_id
            )
        return SubmitResult(
            task_id=task_id,
            task_info=task_info,
            row_count=len(server_rows),
            results=list(resp.results or []),
        )

    def query(self, task_id: str) -> TaskSnapshot:
        """查询单次任务状态（不轮询）。网络/业务失败抛 ``OrganizeTaskError``。"""
        request = PhotoOrganizeQueryRequest(task_id=task_id)
        try:
            resp: PhotoOrganizeQueryResponse = (
                self.dispatcher.operation.query_photo_organize_task(request)
            )
        except OrganizeTaskError:
            raise
        except Exception as exc:
            raise OrganizeTaskError(
                f'查询整理任务失败：{exc}；请停止并交用户决策，勿自动重试'
            ) from exc
        _check_business(resp, '查询整理任务')
        return _snapshot_from_query(resp, task_id)

    def retry(self, task_id: str) -> RetryResult:
        """重试失败/部分失败的任务（不重试 HTTP）。

        服务端码 ``10030814``（已成功无需重试）→ ``skipped=True``，不抛错。
        网络/其它业务失败抛 ``OrganizeTaskError``。
        """
        request = PhotoOrganizeRetryRequest(task_id=task_id)
        try:
            resp: PhotoOrganizeRetryResponse = (
                self.dispatcher.operation.retry_photo_organize_task(request)
            )
        except OrganizeTaskError as exc:
            if exc.code == CODE_ALREADY_SUCCESS:
                return RetryResult(task_id=task_id, skipped=True)
            raise
        except Exception as exc:
            # 部分实现把业务码放在 RuntimeError 里；检查是否含 10030814
            if CODE_ALREADY_SUCCESS in str(exc):
                return RetryResult(task_id=task_id, skipped=True)
            raise OrganizeTaskError(
                f'重试整理任务失败：{exc}；请停止并交用户决策，勿自动重试'
            ) from exc
        _check_business(resp, '重试整理任务')
        return RetryResult(
            task_id=task_id,
            skipped=False,
            task_info=_snapshot_from_retry(resp, task_id),
        )


def _coerce_query_resp(submit_resp: PhotoOrganizeSubmitResponse) -> PhotoOrganizeQueryResponse:
    """submit 的同步终态 ``task_info`` 与 query 同结构，转成 query 响应复用快照构造。

    ``raw`` 是服务端原始嵌套响应（``taskInfo``/``results`` 在 ``data`` 层），必须走
    ``from_response`` 展平后校验——直接 ``model_validate`` 会丢 ``data`` 层。
    """
    return PhotoOrganizeQueryResponse.from_response(
        submit_resp.raw if hasattr(submit_resp, 'raw') else {},
        submit_resp.trace_id,
    )
