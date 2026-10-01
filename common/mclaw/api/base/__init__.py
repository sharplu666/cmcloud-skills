#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.api.base —— 基础类模版。"""

from mclaw.api.base.base_sync_api import BaseSyncApi, SyncRequest, SyncResponse
from mclaw.api.base.base_async_api import (
    AsyncSubmitRequest,
    AsyncSubmitResponse,
    AsyncPollResponse,
    BaseAsyncApi,
)
from mclaw.api.base.base_xml_api import BaseXmlSyncApi, XmlRequest, XmlResponse
from mclaw.api.base._ai_space_log import (
    append_ai_space_log,
    append_ai_space_log_record,
    get_ai_space_log_path_for_output,
    reset_ai_space_log,
    resolve_ai_space_log_path,
)

__all__ = [
    'BaseSyncApi',
    'SyncRequest',
    'SyncResponse',
    'BaseAsyncApi',
    'AsyncSubmitRequest',
    'AsyncSubmitResponse',
    'AsyncPollResponse',
    'BaseXmlSyncApi',
    'XmlRequest',
    'XmlResponse',
    'append_ai_space_log',
    'append_ai_space_log_record',
    'get_ai_space_log_path_for_output',
    'reset_ai_space_log',
    'resolve_ai_space_log_path',
]
