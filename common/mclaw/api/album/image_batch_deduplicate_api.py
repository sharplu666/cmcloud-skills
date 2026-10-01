#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量图片去重（异步任务：提交 + 结果查询）。

对个人云图片执行批量去重：提交接口上传 fileId 文本文件（multipart/form-data，
每行一个 fileId、UTF-8），服务端异步处理并返回 ``taskId``；结果接口按
``taskId`` 查询任务状态、处理统计与结果文件 EOS 下载链接（``respUrl``）。

与同步版 ``image_deduplicate``（单次 ≤1000、请求即返回 ``nonsimilarFileIdList``）
互补：本对接口走异步任务，适合大批量去重。

API 层不内置轮询：调用方先 submit 拿 ``taskId``，再按自身节奏查 result 直到
``task_status`` 进入终态（2-已完成 / 3-失败 / 4-已过期）。

结果文件口径（实测）：``respUrl`` 为 EOS 预签名外链（GET 下载、无需鉴权、
7 天有效）；内容为 zip，内含单个 ``dedupResult-<taskId>.txt``，UTF-8 文本、
每行一个 fileId。**result 查询命中已完成（taskStatus=2 且 respUrl 有值）时
自动内存下载并解析结果文件**（``fetch_result_file_ids``，全程不落盘），解析
出的 fileId 列表挂响应 ``result_file_ids``，下载+解析成功合并打单条 status_log
（字节数 + 个数 + 脱敏清单，trace_id 可跟踪；清单按 ``*``+末 4 位脱敏，
与 submit 侧全量明文清单按后 4 位对账）；下载/解析失败置 ``None`` + fail 日志、
不上抛（result 查询本身成功不应抛）。消费方（``ImageDeduplicator`` 批量优先
路径）取 ``result_file_ids`` 与入参的交集作为保留集。

错误码（附录）：10030009 文件下载失败 / 100300112 MQ 发送异常 /
10030001 上传 EOS 生产外链失败。
"""

from __future__ import annotations

import io
import traceback
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header, get_album_multipart_header
from mclaw.api.base._http import post_multipart_with_retry
from mclaw.utils.settings import ApiTimeoutSettings

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger, status_log
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.album')

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)


__all__ = [
    'DEDUP_TASK_STATUS_PENDING',
    'DEDUP_TASK_STATUS_PROCESSING',
    'DEDUP_TASK_STATUS_COMPLETED',
    'DEDUP_TASK_STATUS_FAILED',
    'DEDUP_TASK_STATUS_EXPIRED',
    'DEDUP_TASK_TERMINAL_STATUSES',
    'IMAGE_BATCH_DEDUP_DOWNLOAD_TIMEOUT',
    'ImageBatchDeduplicateSubmitRequest',
    'ImageBatchDeduplicateSubmitResponse',
    'ImageBatchDeduplicateSubmitApi',
    'ImageBatchDeduplicateResultRequest',
    'ImageBatchDeduplicateResultResponse',
    'ImageBatchDeduplicateResultApi',
    'fetch_result_file_ids',
    '_mask_file_id',
]


#: result 接口 ``taskStatus``：0-待处理
DEDUP_TASK_STATUS_PENDING: int = 0
#: result 接口 ``taskStatus``：1-处理中
DEDUP_TASK_STATUS_PROCESSING: int = 1
#: result 接口 ``taskStatus``：2-已完成（``respUrl`` 有值）
DEDUP_TASK_STATUS_COMPLETED: int = 2
#: result 接口 ``taskStatus``：3-失败（``failCode`` / ``failReason`` 有值）
DEDUP_TASK_STATUS_FAILED: int = 3
#: result 接口 ``taskStatus``：4-已过期
DEDUP_TASK_STATUS_EXPIRED: int = 4

#: 任务终态集合（result 轮询到此集合即可停止）
DEDUP_TASK_TERMINAL_STATUSES: Tuple[int, ...] = (
    DEDUP_TASK_STATUS_COMPLETED,
    DEDUP_TASK_STATUS_FAILED,
    DEDUP_TASK_STATUS_EXPIRED,
)

#: respUrl 结果文件下载超时 ``(connect, read)``（秒）：connect 短超时秒判死不可达
#: （黑洞不再白等），read 容忍弱网传输间隔（KB 级文件防瞬断误杀；
#: 2026-09-11 定案：单值 60 拆对为 5/30）。
IMAGE_BATCH_DEDUP_DOWNLOAD_TIMEOUT: Tuple[float, float] = (5.0, 30.0)


def _mask_file_id(file_id: Any) -> str:
    """fileId 日志打码：``*``+末 4 位（如 ``*ikBA``），空值打 ``*``。

    与 ``select_image_api.format_select_photo_entry`` 同一打码口径；长度不足 4
    位的短 id 整体跟在 ``*`` 后。仅用于 result 侧日志清单脱敏——submit 侧
    ``to_log_dict`` 仍落完整清单（精确定位/重提用，可按后 4 位与本侧对账）。
    """
    text = str(file_id or '')
    return ('*' + text[-4:]) if text else '*'


def fetch_result_file_ids(resp_url: str) -> Tuple[List[str], int]:
    """下载 ``respUrl`` 结果 zip 并读出 txt 内逐行 fileId（全程内存，不落盘）。

    ``respUrl`` 为 EOS 预签名外链（7 天有效），zip 内单个 ``dedupResult-<taskId>.txt``、
    每行一个 fileId；解码用 ``utf-8-sig`` 防 BOM 粘在首个 id 上（否则首个 id 匹配
    不上入参被静默错杀）。任何异常向上抛，由调用方（result API execute）收敛为
    ``result_file_ids=None`` + fail 日志。独立模块级函数，便于测试 monkeypatch。

    返回 ``(fileId 列表, 下载字节数)``；本函数不打日志——下载/解析终态由调用方
    合并成单条 status_log（拿到 URL 与失败日志也在调用方）。
    """
    download = requests.get(resp_url, timeout=IMAGE_BATCH_DEDUP_DOWNLOAD_TIMEOUT)
    download.raise_for_status()
    lines: List[str] = []
    with zipfile.ZipFile(io.BytesIO(download.content)) as zf:
        txt_names = [name for name in zf.namelist() if name.endswith('.txt')]
        if not txt_names:
            raise RuntimeError(f'结果 zip 内无 txt 成员: {zf.namelist()}')
        for name in txt_names:
            text = zf.read(name).decode('utf-8-sig', errors='replace')
            lines.extend(line.strip() for line in text.splitlines())
    return [line for line in lines if line], len(download.content)


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class ImageBatchDeduplicateSubmitRequest(BaseModel):
    """提交批量去重任务的入参（multipart 文件由 fileId 列表派生）。

    接口要求上传文本文件（每行一个 fileId、UTF-8）；本模型收 ``file_id_list``，
    ``to_form`` 内部逐行拼接为文件内容，调用方无需自己落盘。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    file_id_list: List[str] = Field(..., alias='fileIdList', min_length=1)

    def to_form(
        self,
    ) -> Tuple[Dict[str, Any], List[Tuple[str, Tuple[str, Any, str]]]]:
        """构造 multipart 表单 ``(data, files)``：无普通字段，仅一个 ``file`` 文件字段。"""
        content = ('\n'.join(self.file_id_list) + '\n').encode('utf-8')
        files: List[Tuple[str, Tuple[str, Any, str]]] = [
            ('file', ('file_ids.txt', content, 'text/plain')),
        ]
        return {}, files

    def to_log_dict(self) -> Dict[str, Any]:
        """日志落盘用：完整 fileId 列表（即上传文件的逐行内容，单行可 grep）。"""
        return {'fileIdList': list(self.file_id_list)}


class ImageBatchDeduplicateResultRequest(BaseModel):
    """查询批量去重任务结果的入参。"""

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    task_id: str = Field(..., alias='taskId', min_length=1)

    def to_payload(self) -> Dict[str, Any]:
        """输出接口要求的 JSON payload。"""
        return {'taskId': self.task_id}


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class _OpenclawEnvelopeResponse(SyncResponse):
    """openclaw dedup 信封的响应基类（提交 / 结果两接口共用 ``taskId``）。

    实测信封为 ``{success, code, message, data}``；文档标注的 ``msg`` 作兜底
    映射（``msg → message``，保持调用方读 ``.message`` 的统一口径）。真实回包
    ``data.taskId`` 为**整型**（文档标 String），统一无损转 ``str``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_id: str = Field('', alias='taskId')

    @field_validator('task_id', mode='before')
    @classmethod
    def _coerce_task_id(cls, value: Any) -> Any:
        """真实回包 taskId 为整型（文档标 String），统一转 str。"""
        if value is None:
            return ''
        return str(value)

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> '_OpenclawEnvelopeResponse':
        data = raw.get('data') or {}
        merged = {**raw, **data, 'trace_id': trace_id}
        if not str(merged.get('message') or ''):
            merged['message'] = str(merged.get('msg') or '')
        if 'success' not in merged:
            merged['success'] = str(merged.get('code')) == '0000'
        instance = cls.model_validate(merged)
        object.__setattr__(instance, 'raw', raw)
        return instance


class ImageBatchDeduplicateSubmitResponse(_OpenclawEnvelopeResponse):
    """提交批量去重任务的响应（``data.taskId`` 展平后自动填充 ``task_id``）。"""


class ImageBatchDeduplicateResultResponse(_OpenclawEnvelopeResponse):
    """查询批量去重任务结果的响应。

    ``task_status`` 见模块级 ``DEDUP_TASK_STATUS_*`` 常量；``resp_url`` 仅
    已完成（2）时返回，``fail_code`` / ``fail_reason`` 仅失败（3）时返回，
    其余状态为 None。``result_file_ids`` 由 ``execute`` 在已完成态自动下载
    解析结果文件填充（下载/解析失败保持 None，配合 fail 日志）。
    """

    task_status: int = Field(0, alias='taskStatus')
    files_number: int = Field(0, alias='filesNumber')
    success_number: int = Field(0, alias='successNumber')
    resp_url: Optional[str] = Field(None, alias='respUrl')
    result_file_ids: Optional[List[str]] = None
    fail_code: Optional[str] = Field(None, alias='failCode')
    fail_reason: Optional[str] = Field(None, alias='failReason')
    create_time: str = Field('', alias='createTime')
    update_time: str = Field('', alias='updateTime')

    @property
    def is_terminal(self) -> bool:
        """是否终态（2-已完成 / 3-失败 / 4-已过期）。"""
        return self.task_status in DEDUP_TASK_TERMINAL_STATUSES

    @property
    def is_success(self) -> bool:
        """是否成功（task_status == 2）。"""
        return self.task_status == DEDUP_TASK_STATUS_COMPLETED


# ──────────────────────────── API 类 ────────────────────────────


@album_api_registry.register('image_batch_deduplicate_submit')
class ImageBatchDeduplicateSubmitApi(BaseSyncApi):
    """提交批量去重任务（multipart/form-data，同步返回 taskId）。

    重写 ``execute`` 走 multipart 路径（不能走 ``post_json_with_retry``）；
    响应解析走 ``_parse_response`` → ``_build_result``，复用终态日志、脱敏。
    """

    PATH = '/richlifeApp/api/openclaw/deduplicate/submit'
    TIMEOUT = ApiTimeoutSettings.IMAGE_BATCH_DEDUP_SUBMIT_SEC

    api_category = 'album'
    api_label = '批量图片去重-提交任务'

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        super().__init__(host, auth_fn, logger, redact_params)
        # multipart 不设 Content-Type（由 requests 生成含 boundary 的头）
        self._auth = get_album_multipart_header

    def execute(
        self,
        request: ImageBatchDeduplicateSubmitRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ImageBatchDeduplicateSubmitResponse:
        """发起一次 multipart 提交，返回包含 ``task_id`` 的响应。"""
        url = self._resolve_url(self.PATH)
        data, files = request.to_form()
        extra_info = info_dict if isinstance(info_dict, dict) else {}
        log_data = request.to_log_dict()

        try:
            raw, trace_id = post_multipart_with_retry(
                url,
                data,
                files,
                auth_fn=self._auth,
                timeout=kwargs.get('timeout', self.TIMEOUT),
                max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
                retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
                logger=self.logger,
                log_payload=log_data,
            )
            response = self._parse_response(raw, trace_id, *args, **kwargs)
            msg = self._format_result_msg(response, url, 'execute', *args, **kwargs)
        except Exception:
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[{type(self).__name__}] parse/format FAILED. data={log_data}. exc={flat_exc}',
                logger=self.logger,
                info_dict={'api': type(self).__name__, **extra_info},
                server_type='SYNC',
                stdout=True,
            )
            raise

        status_log(
            msg=msg,
            logger=self.logger,
            info_dict={'api': type(self).__name__, 'trace_id': trace_id, **extra_info},
            server_type='SYNC',
        )
        return self._build_result(response, raw, trace_id, *args, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ImageBatchDeduplicateSubmitResponse:
        """类型化响应解析：返回 ``ImageBatchDeduplicateSubmitResponse``。"""
        return ImageBatchDeduplicateSubmitResponse.from_response(raw, trace_id)


@album_api_registry.register('image_batch_deduplicate_result')
class ImageBatchDeduplicateResultApi(BaseSyncApi):
    """查询批量去重任务结果（JSON POST，单次查询，不轮询）。"""

    PATH = '/richlifeApp/api/openclaw/deduplicate/result'
    TIMEOUT = ApiTimeoutSettings.IMAGE_BATCH_DEDUP_RESULT_SEC

    api_category = 'album'
    api_label = '批量图片去重-查询结果'

    @staticmethod
    def _response_success(response: Any) -> bool:
        """查询级成功判定：只看信封 ``success``（= code 0000），与无 ``is_success``
        属性的同步 API 口径一致。

        基类默认优先用响应的 ``is_success``（本响应类定义为 ``taskStatus==2``
        任务级完成），会把「任务处理中」的健康查询判成 fail——既打 WARNING
        fail 日志，又经 ``record_cli_business_fail`` 记进 failapi（CLI 回执的
        失败接口清单）。任务终态由调用方（编排层轮询）与 result 内容承载，
        不进请求级判定。
        """
        return bool(getattr(response, 'success', False))

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_album_header

    def execute(
        self,
        request: ImageBatchDeduplicateResultRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ImageBatchDeduplicateResultResponse:
        """类型化入口：标准同步链后，已完成态自动下载解析结果文件。"""
        resp = super().execute(request, *args, info_dict=info_dict, **kwargs)
        return self._attach_result_file_ids(resp)

    def _attach_result_file_ids(
        self, resp: ImageBatchDeduplicateResultResponse
    ) -> ImageBatchDeduplicateResultResponse:
        """``taskStatus=2`` 且 ``respUrl`` 有值 → 内存下载解析挂 ``result_file_ids``。

        日志两步：拿到 respUrl 一条；下载并解析成功合并打一条（字节数 +
        fileId 个数 + 脱敏清单，trace_id 复用 result 查询的——EOS 下载无独立
        tid；脱敏清单与 submit 侧明文清单按后 4 位对账）。下载/解析失败置
        ``None`` + fail 日志、不上抛：result 查询本身成功不应抛，终态语义由
        调用方判 ``result_file_ids`` 承载。
        """
        if not getattr(resp, 'is_success', False) or not str(resp.resp_url or ''):
            return resp
        base_info = {
            'api': type(self).__name__,
            'trace_id': str(getattr(resp, 'trace_id', '') or ''),
            'task_id': str(resp.task_id or ''),
            'resp_url': str(resp.resp_url or ''),
        }
        status_log(
            msg=f'[{type(self).__name__}] 拿到去重结果文件 respUrl: {resp.resp_url}',
            logger=self.logger,
            info_dict=base_info,
            server_type='SYNC',
        )
        try:
            file_ids, nbytes = fetch_result_file_ids(str(resp.resp_url))
            resp.result_file_ids = file_ids
            status_log(
                msg=f'[{type(self).__name__}] 去重结果文件下载并解析成功: '
                f'{nbytes} 字节, {len(file_ids)} 个 fileId',
                logger=self.logger,
                info_dict={**base_info, 'bytes': nbytes,
                           'file_ids': [_mask_file_id(x) for x in file_ids]},
                server_type='SYNC',
            )
        except Exception:  # noqa: BLE001 - 下载/解析失败不上抛，置 None 由调用方回退
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[{type(self).__name__}] fetch respUrl FAILED. '
                f'taskId={resp.task_id}. exc={flat_exc}',
                logger=self.logger,
                info_dict=base_info,
                server_type='SYNC',
            )
        return resp

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> ImageBatchDeduplicateResultResponse:
        """类型化响应解析：返回 ``ImageBatchDeduplicateResultResponse``。"""
        return ImageBatchDeduplicateResultResponse.from_response(raw, trace_id)
