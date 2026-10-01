#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回忆/故事相册内图片列表查询（同步接口）。

接口路径：POST /richlifeApp/personalSaas/album/story/memory/file/list

查询指定回忆/故事相册内的图片文件列表。响应结构特殊，文件列表嵌套在
``data.file.list`` 中（三重嵌套：``data`` → ``file`` → ``list[]`` → ``fileInfo``）。

接口文档：dev/docs/api/cm-cloud-album.md §11

响应说明：
  本接口响应有三重嵌套层级：``data.file.list[].fileInfo``，标准文件字段
  位于 ``fileInfo`` 内层。此外：

  - ``totalCount`` 可能在 **两个位置之一**：``data.totalCount`` 或
    ``data.file.totalCount``，``from_response`` 必须检查两处兜底。
  - ``nextPageCursor`` 位于 ``data.file.nextPageCursor``（比单层嵌套接口深一层）。

  基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层后
  ``model_validate``，无法识别此三重嵌套 + 双位置 totalCount 结构，故**必须
  重写 ``from_response``** 手动遍历 ``data.file.list[]``，提取每项的
  ``fileInfo`` 展平为 ``List[FileInfo]``，并检查两处 ``totalCount``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header
from mclaw.api.album._models import FileInfo, PageInfo


__all__ = [
    'StoryMemoryFileListRequest',
    'StoryMemoryFileListResponse',
    'StoryMemoryFileListApi',
]


# ──────────────────────────── 入参 BaseModel ────────────────────────────


class StoryMemoryFileListRequest(BaseModel):
    """回忆/故事相册内图片列表查询接口入参。

    本接口属于 cloudId 体系（参数为 ``albumId``/``pageInfo``），与媒体发送型
    基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/sourceTaskId）字段
    不重合，故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        album_id: 回忆/故事相册 ID（必填）。
        page_info: 游标分页信息。
        order_by: 排序字段，``'1'``=拍摄/上传时间，``'2'``=创建时间。默认 ``'1'``。
        order_direction: 排序方向，``'1'``=倒序，``'2'``=正序。默认 ``'1'``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    album_id: str = Field(..., alias='albumId')
    page_info: PageInfo = Field(..., alias='pageInfo')
    order_by: str = Field('1', alias='orderBy')
    order_direction: str = Field('1', alias='orderDirection')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。"""
        return {
            'albumId': self.album_id,
            'orderBy': self.order_by,
            'orderDirection': self.order_direction,
            'pageInfo': self.page_info.model_dump(by_alias=True, exclude_none=True),
        }


# ──────────────────────────── 出参 BaseModel ────────────────────────────


class StoryMemoryFileListResponse(SyncResponse):
    """回忆/故事相册内图片列表查询出参（同步返回）。

    扩展字段对应响应 ``data`` 内的业务字段：
      - ``next_page_cursor``：下一页游标，位于 ``data.file.nextPageCursor``，
        最后一页为空串。
      - ``total_count``：文件总数，可能在 ``data.totalCount`` 或
        ``data.file.totalCount`` 两个位置之一，``from_response`` 会检查两处兜底。
      - ``file_list``：文件信息列表（``List[FileInfo]``），已从
        ``data.file.list[].fileInfo`` 三重嵌套结构中展平提取。

    响应为三重嵌套结构（``data`` → ``file`` → ``list[]`` → ``fileInfo``），
    且 ``totalCount`` 有两个可能位置，基类 ``SyncResponse.from_response`` 默认
    展平 ``data`` 后无法识别此结构，故必须重写 ``from_response``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    next_page_cursor: str = Field('', alias='nextPageCursor')
    total_count: int = Field(0, alias='totalCount')
    file_list: List[FileInfo] = Field(default_factory=list, alias='fileList')

    @classmethod
    def from_response(
        cls,
        raw: Dict[str, Any],
        trace_id: str = '',
    ) -> 'StoryMemoryFileListResponse':
        """从原始响应构造，手动解析三重嵌套 + 双位置 totalCount 兜底。

        响应结构 ``data.file.list[].fileInfo``（三重嵌套），标准文件字段在
        ``fileInfo`` 内层。``totalCount`` 可能位于 ``data.totalCount`` 或
        ``data.file.totalCount``，需检查两处兜底。``nextPageCursor`` 位于
        ``data.file.nextPageCursor``。

        本方法：
          1. 取 ``data`` → ``data.file`` 两层嵌套
          2. ``totalCount`` 先查 ``data.totalCount``，缺失则查 ``data.file.totalCount``
          3. 遍历 ``data.file.list[]``，逐项提取 ``fileInfo`` 展平为 ``List[FileInfo]``
          4. ``nextPageCursor`` 从 ``data.file.nextPageCursor`` 取
        """
        data = (raw or {}).get('data') or {}
        file_data = data.get('file') or {}  # 嵌套层

        # totalCount 双位置兜底：data.totalCount 优先，缺失则取 data.file.totalCount
        total_raw = data.get('totalCount')
        if total_raw is None:
            total_raw = file_data.get('totalCount')
        try:
            total_int = int(total_raw) if total_raw is not None else 0
        except (TypeError, ValueError):
            total_int = 0

        # nextPageCursor 在 data.file.nextPageCursor
        next_cursor = str(file_data.get('nextPageCursor') or '')

        # 遍历 data.file.list[] 提取 fileInfo
        file_list: List[FileInfo] = []
        for row in file_data.get('list') or []:
            fi = row.get('fileInfo') if isinstance(row, dict) else None
            if fi:
                file_list.append(FileInfo.model_validate(fi))

        instance = cls(
            success=(
                bool(raw.get('success'))
                if 'success' in raw
                else str(raw.get('code')) == '0000'
            ),
            code=raw.get('code', ''),
            message=raw.get('message', ''),
            trace_id=trace_id,
            next_page_cursor=next_cursor,
            total_count=total_int,
            file_list=file_list,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


# ──────────────────────────── API 子类 ────────────────────────────


@album_api_registry.register('story_memory_file_list')
class StoryMemoryFileListApi(BaseSyncApi):
    """回忆/故事相册内图片列表查询的同步 API。

    路径 ``POST /richlifeApp/personalSaas/album/story/memory/file/list``，
    请求即返回最终结果（``file_list`` + ``next_page_cursor``），无 ``taskId``
    轮询。

    Response 字段扩展了 ``file_list``（``List[FileInfo]``），与基类
    ``SyncResponse`` 不一致，且响应为三重嵌套结构
    （``data.file.list[].fileInfo``）需手动展平，``totalCount`` 需双位置兜底，
    故必须类型化 ``execute`` 签名 + 重写 ``_parse_response`` 指向
    ``StoryMemoryFileListResponse``。

    与 legacy ``cm_cloud_http.py`` ``api_story_memory_file_list``（lines 365-389）
    对齐：legacy 层手写解析三重嵌套 + 双位置 totalCount 兜底
    （``data.get('totalCount')`` 缺失则取 ``data.file.totalCount``），
    本实现以 ``from_response`` 重写等价完成。
    """

    PATH = '/richlifeApp/personalSaas/album/story/memory/file/list'

    api_category = 'album'
    api_label = '回忆/故事相册内图片'

    def __init__(
        self,
        host: str,
        auth_fn: Any,
        logger: Any = None,
        redact_params: Optional[List[str]] = None,
    ) -> None:
        """注入相册端点专用鉴权头。

        覆盖 ``self._auth`` 为 ``get_album_header``（在标准云盘鉴权头基础上
        追加 ``Content-Type`` / ``x-yun-client-info``），对齐 legacy
        ``cm_cloud_http.py`` 的 ``_send_request(header_type='json')`` 链路。
        ``get_album_header`` 每次调用都重读 ``.env``，token 文件更新后
        下次请求即生效。
        """
        super().__init__(host, auth_fn, logger, redact_params)
        self._auth = get_album_header

    def execute(
        self,
        request: StoryMemoryFileListRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> StoryMemoryFileListResponse:
        """类型化入口：入参指向 ``StoryMemoryFileListRequest``，返回
        ``StoryMemoryFileListResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展了 ``file_list`` 且需手动展平三重嵌套 ``fileInfo`` 包装，
        均与基类不一致，故必须类型化覆盖 execute 签名。实际流程通过
        ``super().execute`` 转发，响应类型转换由重写的 ``_parse_response``
        完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> StoryMemoryFileListResponse:
        """重写基类钩子：用 ``StoryMemoryFileListResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``file_list``）及三重嵌套
        ``fileInfo`` 包装结构 + 双位置 ``totalCount`` 兜底。本方法改用子类的
        ``from_response``，其内部遍历 ``data.file.list[]`` 提取 ``fileInfo``
        展平为 ``List[FileInfo]``，并检查两处 ``totalCount``。
        """
        return StoryMemoryFileListResponse.from_response(raw, trace_id)
