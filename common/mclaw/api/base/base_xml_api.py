#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XML 同步接口基类。

外链部分接口仍是 ``resultCode`` + ElementTree，与 JSON ``BaseSyncApi`` 并列。
业务失败记 failapi 后返回 ``success=False``，由调用方决定是否抛错。
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
import traceback
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from mclaw.api.base._base_api import _BaseApi
from mclaw.api.base._http import post_xml_with_retry, record_cli_business_fail

try:
    from mclaw.utils.logger import openclaw_logger as _default_logger, status_log
except Exception:  # pragma: no cover
    import logging
    _default_logger = logging.getLogger('mclaw.api.xml')

    def status_log(msg, logger=None, info_dict=None, server_type='API'):
        info_dict = info_dict or {}
        line = f"{server_type}|||{msg}|" + ''.join(f"{k}:{v}|" for k, v in info_dict.items())
        level = logging.WARNING if ('fail' in str(msg) or 'error' in str(msg)) else logging.INFO
        (logger or _default_logger).log(level, line)


__all__ = ['XmlRequest', 'XmlResponse', 'BaseXmlSyncApi']

_XML_CONTENT_TYPE = 'text/xml;UTF-8'
_XML_USER_AGENT = 'Java/1.5.0_06'
_XML_OK_CODES = ('0', '0000')


class XmlRequest(BaseModel):
    """XML 接口入参基类。子类实现 ``to_xml()``。"""

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    def to_xml(self) -> str:
        raise NotImplementedError


@dataclass
class XmlResponse:
    """XML 接口出参：保留 ElementTree 根节点供业务解析。"""

    root: ET.Element
    raw_xml: str
    trace_id: str = ''
    result_code: str = ''
    message: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.result_code in _XML_OK_CODES


class BaseXmlSyncApi(_BaseApi, ABC):
    """XML POST 同步基类。子类必须设置 ``PATH``，Request 实现 ``to_xml()``。"""

    PATH: str = ''

    def __init__(
        self,
        host: str,
        auth_fn: Callable[[], Dict[str, str]],
        logger=None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        if not self.PATH:
            raise ValueError(f'{type(self).__name__}.PATH 未设置')
        super().__init__(host, auth_fn, logger, redact_params)

    def _xml_headers(self) -> Dict[str, str]:
        headers = dict(self._auth() if self._auth else {})
        headers['Content-Type'] = _XML_CONTENT_TYPE
        headers['User-Agent'] = _XML_USER_AGENT
        return headers

    def execute(
        self,
        request: XmlRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> XmlResponse:
        url = self._resolve_url(self.PATH)
        xml_body = request.to_xml()
        extra_info = info_dict if isinstance(info_dict, dict) else {}
        text, trace_id = post_xml_with_retry(
            url,
            xml_body,
            auth_fn=self._xml_headers,
            timeout=kwargs.get('timeout', self.TIMEOUT),
            max_retries=kwargs.get('max_retries', self.MAX_RETRIES),
            retry_delay=kwargs.get('retry_delay', self.RETRY_DELAY),
            logger=self.logger,
        )
        try:
            response = self._parse_xml(text, trace_id)
            msg = self._format_result_msg(response, url, 'execute', *args, **kwargs)
            if not response.success:
                record_cli_business_fail(
                    '/' + self.PATH.lstrip('/'),
                    response.message or '业务失败',
                    request=xml_body,
                    response=response.raw_xml,
                )
        except Exception:
            flat_exc = ' '.join(traceback.format_exc().split())
            status_log(
                msg=f'[{type(self).__name__}] parse/format FAILED. payload={xml_body}. exc={flat_exc}',
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
        return response

    def _parse_xml(self, text: str, trace_id: str) -> XmlResponse:
        # HTTP 层已校验 well-formed；这里取 root 与 resultCode。
        root = ET.fromstring(text)
        result_code = str(root.get('resultCode') or '').strip()
        ok = result_code in _XML_OK_CODES
        return XmlResponse(
            root=root,
            raw_xml=text,
            trace_id=trace_id,
            result_code=result_code,
            message='' if ok else (text or '业务失败'),
            raw={'resultCode': result_code, 'xml': text},
        )
