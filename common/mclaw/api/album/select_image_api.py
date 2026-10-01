#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 选图（异步任务：提交 + 结果查询）。

对个人云图片执行 AI 精选：提交接口上传 imageIdFile（multipart/form-data，
每行一个 ``{"fileId":"xxx","score":"1.0"}`` JSON），可附带 ``query``（选图
意图）/ ``count``（选图数量，服务端默认 50）/ ``threshold``（质量评分阈值，
服务端默认 50）；服务端异步处理并返回 ``taskId``。结果接口按 ``taskId``
查询任务状态（1-PENDING 2-RUNNING 3-SUCCESS 4-FAILED 5-CANCELLED）与
结果文件 ``resultUrl``（JSON：``goodImages`` / ``badImages``，每项
``{"fileId","score"}``）。

API 层不内置轮询：调用方先 submit 拿 ``taskId``，再按自身节奏查 result
直到 ``status`` 进入终态（3/4/5）。

resultUrl 消费口径：查询接口 execute 在任务成功（status=3）且携带
``resultUrl`` 时，**内存直读**（``requests.get`` → ``json()``，不落盘），
解析结果挂到响应的 ``good_images`` / ``bad_images`` 供调用方消费，并随
终态日志一起打印；为控制日志体积，fileId 打码为 ``*``+末 4 位、score
格式化为 float 保留 2 位小数。
"""

from __future__ import annotations

import json
import traceback
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
    'SELECT_PHOTO_STATUS_PENDING',
    'SELECT_PHOTO_STATUS_RUNNING',
    'SELECT_PHOTO_STATUS_SUCCESS',
    'SELECT_PHOTO_STATUS_FAILED',
    'SELECT_PHOTO_STATUS_CANCELLED',
    'SELECT_PHOTO_TERMINAL_STATUSES',
    'SelectPhotoItem',
    'SelectPhotoSubmitRequest',
    'SelectPhotoSubmitResponse',
    'SelectPhotoSubmitApi',
    'SelectPhotoResultRequest',
    'SelectPhotoResultResponse',
    'SelectPhotoResultApi',
]


#: result 接口 ``status``：1-待处理
SELECT_PHOTO_STATUS_PENDING: int = 1
#: result 接口 ``status``：2-处理中
SELECT_PHOTO_STATUS_RUNNING: int = 2
#: result 接口 ``status``：3-成功（``resultUrl`` 有值）
SELECT_PHOTO_STATUS_SUCCESS: int = 3
#: result 接口 ``status``：4-失败
SELECT_PHOTO_STATUS_FAILED: int = 4
#: result 接口 ``status``：5-已取消
SELECT_PHOTO_STATUS_CANCELLED: int = 5

#: 任务终态集合（result 轮询到此集合即可停止）
SELECT_PHOTO_TERMINAL_STATUSES: Tuple[int, ...] = (
    SELECT_PHOTO_STATUS_SUCCESS,
    SELECT_PHOTO_STATUS_FAILED,
    SELECT_PHOTO_STATUS_CANCELLED,
)


def format_select_photo_entry(item: Dict[str, Any]) -> str:
    """结果清单打码格式：fileId → ``*``+末 4 位，score → float 去尾零（最多 2 位小数）。

    输出形如 ``*ikBA:0.9`` / ``*ikBA:0.91``；score 缺失或不可解析时只输出
    打码 fileId。
    """
    file_id = str(item.get('fileId') or '')
    masked = ('*' + file_id[-4:]) if file_id else '*'
    score = item.get('score')
    if score is None:
        return masked
    try:
        return f'{masked}:{float(score):.2f}'.rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return masked


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class SelectPhotoItem(BaseModel):
    """imageIdFile 单行记录：``{"fileId":"xxx","score":"1.0"}``。"""

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    file_id: str = Field(..., alias='fileId', min_length=1)
    score: str = Field('1.0', alias='score')

    @field_validator('score', mode='before')
    @classmethod
    def _coerce_score(cls, value: Any) -> Any:
        """调用方常持 float 分值，入模统一转 str（接口口径）。"""
        if value is None:
            return '1.0'
        if isinstance(value, float):
            return f'{value:.1f}'
        return str(value)

    def to_line(self) -> str:
        """输出接口要求的单行紧凑 JSON。"""
        return json.dumps(
            {'fileId': self.file_id, 'score': self.score},
            ensure_ascii=False,
            separators=(',', ':'),
        )


class SelectPhotoSubmitRequest(BaseModel):
    """提交选图任务的入参（multipart 文件由 fileId+score 列表派生）。

    ``query`` / ``count`` / ``threshold`` 均可选，None 时不出现在表单里
    （由服务端取默认 50 / 50）。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    query: Optional[str] = Field(None, max_length=100)
    count: Optional[int] = Field(None, gt=0)
    threshold: Optional[int] = Field(None, ge=0)
    items: List[SelectPhotoItem] = Field(..., min_length=1)

    def to_form(
        self,
    ) -> Tuple[Dict[str, Any], List[Tuple[str, Tuple[str, Any, str]]]]:
        """构造 multipart 表单 ``(data, files)``：可选字段只带非 None 值。"""
        data: Dict[str, Any] = {}
        if self.query is not None:
            data['query'] = self.query
        if self.count is not None:
            data['count'] = self.count
        if self.threshold is not None:
            data['threshold'] = self.threshold
        content = ('\n'.join(item.to_line() for item in self.items) + '\n').encode('utf-8')
        # 实测服务端校验扩展名：imageIdFile 仅支持 txt（code 01000001）
        files: List[Tuple[str, Tuple[str, Any, str]]] = [
            ('imageIdFile', ('image_ids.txt', content, 'text/plain')),
        ]
        return data, files

    def to_log_dict(self) -> Dict[str, Any]:
        """日志落盘用：全量打码清单（fileId ``*``+末 4 位、score 2 位小数）。

        与 result 接口终态日志的打码口径一致（``format_select_photo_entry``）。
        """
        return {
            'query': self.query,
            'count': self.count,
            'threshold': self.threshold,
            'imageCount': len(self.items),
            'images': [
                format_select_photo_entry(item.model_dump(by_alias=True))
                for item in self.items
            ],
        }


class SelectPhotoResultRequest(BaseModel):
    """查询选图任务结果的入参。"""

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    task_id: str = Field(..., alias='taskId', min_length=1)

    def to_payload(self) -> Dict[str, Any]:
        """输出接口要求的 JSON payload。"""
        return {'taskId': self.task_id}


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class _SelectPhotoEnvelopeResponse(SyncResponse):
    """选图任务族信封的响应基类（提交 / 结果两接口共用 ``taskId``）。

    信封为 ``{success, code, message, data}``；``success`` 缺失时按 ``code``
    推导（实测成功码为 ``'0000'``，文档标的 ``'0'`` 一并兼容）；文档标注的
    ``msg`` 作兜底映射（``msg → message``）。``data.taskId`` 若为整型统一
    无损转 ``str``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    task_id: str = Field('', alias='taskId')

    @field_validator('task_id', mode='before')
    @classmethod
    def _coerce_task_id(cls, value: Any) -> Any:
        """taskId 整型回包统一转 str。"""
        if value is None:
            return ''
        return str(value)

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> '_SelectPhotoEnvelopeResponse':
        data = raw.get('data') or {}
        merged = {**raw, **data, 'trace_id': trace_id}
        if not str(merged.get('message') or ''):
            merged['message'] = str(merged.get('msg') or '')
        if 'success' not in merged:
            merged['success'] = str(merged.get('code')) in ('0', '0000')
        instance = cls.model_validate(merged)
        object.__setattr__(instance, 'raw', raw)
        return instance


class SelectPhotoSubmitResponse(_SelectPhotoEnvelopeResponse):
    """提交选图任务的响应（``data.taskId`` 展平后自动填充 ``task_id``）。"""


class SelectPhotoResultResponse(_SelectPhotoEnvelopeResponse):
    """查询选图任务结果的响应。

    ``status`` 见模块级 ``SELECT_PHOTO_STATUS_*`` 常量；``result_url`` 仅
    成功（3）时返回。任务成功且 resultUrl 可达时，execute 会把内存解析的
    ``good_images`` / ``bad_images``（原始 ``{"fileId","score"}`` dict 列表）
    挂到本响应上，调用方无需二次下载。
    """

    status: int = Field(0, alias='status')

    @field_validator('status', mode='before')
    @classmethod
    def _coerce_status(cls, value: Any) -> Any:
        """status 字符串回包统一转 int。"""
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    result_url: Optional[str] = Field(None, alias='resultUrl')
    good_images: Optional[List[Dict[str, Any]]] = None
    bad_images: Optional[List[Dict[str, Any]]] = None

    @property
    def is_terminal(self) -> bool:
        """是否终态（3-成功 / 4-失败 / 5-已取消）。"""
        return self.status in SELECT_PHOTO_TERMINAL_STATUSES

    @property
    def is_success(self) -> bool:
        """是否成功（status == 3）。"""
        return self.status == SELECT_PHOTO_STATUS_SUCCESS


# ──────────────────────────── API 类 ────────────────────────────


@album_api_registry.register('select_photo_submit')
class SelectPhotoSubmitApi(BaseSyncApi):
    """提交选图任务（multipart/form-data，同步返回 taskId）。

    重写 ``execute`` 走 multipart 路径（不能走 ``post_json_with_retry``）；
    响应解析走 ``_parse_response`` → ``_build_result``，复用终态日志、脱敏。
    """

    PATH = '/richlifeApp/api/image/asyncSelectPhoto'
    TIMEOUT = ApiTimeoutSettings.SELECT_PHOTO_SUBMIT_SEC

    api_category = 'album'
    api_label = 'AI选图-提交任务'

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
        request: SelectPhotoSubmitRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SelectPhotoSubmitResponse:
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
    ) -> SelectPhotoSubmitResponse:
        """类型化响应解析：返回 ``SelectPhotoSubmitResponse``。"""
        return SelectPhotoSubmitResponse.from_response(raw, trace_id)


@album_api_registry.register('select_photo_result')
class SelectPhotoResultApi(BaseSyncApi):
    """查询选图任务结果（JSON POST，单次查询，不轮询）。

    任务成功（status=3）且携带 ``resultUrl`` 时，``_parse_response`` 内
    内存拉取并解析结果 JSON（不落盘），挂到响应的 ``good_images`` /
    ``bad_images``；``_format_result_msg`` 把打码后的解析清单追加到终态
    日志，与 result 同行输出。
    """

    PATH = '/richlifeApp/api/image/selectPhotoResult'
    TIMEOUT = ApiTimeoutSettings.SELECT_PHOTO_RESULT_SEC

    api_category = 'album'
    api_label = 'AI选图-查询结果'

    @staticmethod
    def _response_success(response: Any) -> bool:
        """查询级成功判定：只看信封 ``success``（= code '0'）。

        基类默认优先用响应的 ``is_success``（本响应类定义为 ``status==3``
        任务级成功），会把「任务处理中」的健康查询判成 fail——既打 WARNING
        fail 日志，又经 ``record_cli_business_fail`` 记进 failapi。任务终态
        由调用方（轮询）与 result 内容承载，不进请求级判定。
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

    @staticmethod
    def _fetch_result_images(result_url: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """内存直读 resultUrl（EOS 预签名外链，GET 无需鉴权），返回 (good, bad)。

        结果文件为 JSON：``{"goodImages":[{"fileId","score"}],"badImages":[...]}``。
        """
        download = requests.get(result_url, timeout=(
            ApiTimeoutSettings.SELECT_PHOTO_DOWNLOAD_CONNECT_SEC,
            ApiTimeoutSettings.SELECT_PHOTO_DOWNLOAD_SEC,
        ))
        download.raise_for_status()
        payload = download.json()
        good = payload.get('goodImages') or []
        bad = payload.get('badImages') or []
        if not isinstance(good, list) or not isinstance(bad, list):
            raise ValueError(f'resultUrl 内容结构异常: goodImages/badImages 非 list')
        return good, bad

    def execute(
        self,
        request: SelectPhotoResultRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SelectPhotoResultResponse:
        """类型化入口：实际流程经 ``super().execute`` 标准同步链。"""
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> SelectPhotoResultResponse:
        """类型化响应解析 + 结果文件内存直读。

        任务成功且带 ``resultUrl`` 时拉取解析并挂载 ``good_images`` /
        ``bad_images``；拉取失败抛异常（交由基类 execute 统一记日志并
        re-raise，轮询调用方按一次查询失败处理）。
        """
        response = SelectPhotoResultResponse.from_response(raw, trace_id)
        if response.success and response.is_success and response.result_url:
            response.good_images, response.bad_images = self._fetch_result_images(
                response.result_url
            )
        return response

    def _format_result_msg(
        self,
        response: Any,
        url: str,
        verb: str,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """终态日志追加打码后的解析清单（fileId ``*``+末 4 位、score 2 位小数）。"""
        msg = super()._format_result_msg(response, url, verb, *args, **kwargs)
        if getattr(response, 'good_images', None) is None:
            return msg
        good = response.good_images or []
        bad = response.bad_images or []
        good_repr = ','.join(format_select_photo_entry(item) for item in good)
        bad_repr = ','.join(format_select_photo_entry(item) for item in bad)
        return (
            f'{msg} parsed: goodImages={len(good)} badImages={len(bad)}'
            f' good=[{good_repr}] bad=[{bad_repr}].'
        )
