#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""相册智能搜索（同步接口，特殊桶 F2）。

跨类型智能搜索相册，支持搜索地点相册、人物相册、事物相册、自定义相册和
回忆/故事相册。通过关键字和类型条件筛选，支持分页和排序。**本接口为同步
接口**——请求即返回最终结果，不需要轮询。

接口文档：dev/docs/api/album/cm_cloud_search_ai_story.md

文档口径差异（2026-08-31 现网实测）：接口文档写 ``resultCode`` / ``rows`` /
``total``，现网实际返回 ``code`` / ``data`` / ``totalRows``（另有 ``message``）。
以现网实测为准，本文档类的 ``code`` / ``data`` / ``totalRows`` 即现网口径。

响应说明（F2 特殊信封）：
  本接口响应与标准信封有 4 处差异，需重写 ``from_response``：

  1. **``code`` 是 int 0**（不是字符串 ``'0000'``）：成功判断 ``code == 0``。
  2. **``data`` 是 flat 数组**（不是对象）：``data: [...]`` 直接是故事相册
     列表，无 ``list`` 包装层。
  3. **``totalRows`` / ``count`` 在顶层**（不在 ``data`` 内）。
  4. **``showInfo`` 分页**（不是 ``pageInfo``）：用 ``startNum`` / ``stopNum``
     表示闭区间（从 1 开始），且 ``sortInfos`` / ``returnTotalCountFlag``
     嵌套在 ``showInfo`` 内（不是请求顶层）。

  基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层（把 ``data``
  内字段提升到顶层），但本接口 ``data`` 是数组而非对象，展平逻辑不适用，
  故必须重写 ``from_response`` 手动解析。

入参/出参子结构全部在本模块内定义，不复用 ``_models.AlbumListItem``
（列表接口用 ``id`` / ``name`` / ``cover``，搜索接口用 ``storyId`` /
``storyName`` / ``coverFileId``，字段名不同，强行复用会埋坑）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from mclaw.api import BaseSyncApi, SyncResponse
from mclaw.api.album import album_api_registry
from mclaw.api.album._get_auth import get_album_header


__all__ = [
    'SearchAIStoryRequest',
    'SearchAIStoryResponse',
    'StorySearchItem',
]


class _Conditions(BaseModel):
    """搜索条件子结构（``conditions`` 对象）。

    Attributes:
        keywords: 搜索关键字列表，空或不传表示不筛选关键字。
        type: 相册类型：``0`` 个人云相册（地点/人物/事物/自定义）；
            ``2`` 回忆故事。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    type: int = Field(..., alias='type')
    keywords: Optional[List[str]] = Field(None, alias='keywords')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        ``keywords`` 仅在非空时包含——空列表或 None 表示不筛选关键字。
        """
        out: Dict[str, Any] = {'type': self.type}
        if self.keywords:
            out['keywords'] = list(self.keywords)
        return out


class _SortInfo(BaseModel):
    """排序信息子结构（``showInfo.sortInfos[]`` 数组项）。

    Attributes:
        field: 排序字段：不传默认 ``updatedAt``；``createdAt`` 按创建时间；
            未传更新时间字段时按 ``storyName`` 名称排序。
        reverse: 排序方向：``True`` 降序；``False`` 升序。
        field_type: 排序字段类型：``3`` String；``4`` int；``5`` float；
            ``6`` long；``7`` double；``8`` short。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    field: Optional[str] = Field(None, alias='field')
    reverse: Optional[bool] = Field(None, alias='reverse')
    field_type: Optional[int] = Field(None, alias='fieldType')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名，过滤 None）。"""
        return self.model_dump(by_alias=True, exclude_none=True)


class _ShowInfo(BaseModel):
    """分页和排序信息（``showInfo`` 对象）。

    与列表接口的游标分页 ``PageInfo`` 不同——``showInfo`` 用 ``startNum`` /
    ``stopNum`` 表示查询区间（闭区间，从 1 开始），且 ``sortInfos`` /
    ``returnTotalCountFlag`` 嵌套在 ``showInfo`` 内（不是请求顶层）。

    Attributes:
        start_num: 起始位置（从 1 开始）。
        stop_num: 结束位置。
        sort_infos: 排序信息列表，空或不传按默认排序。
        return_total_count_flag: 是否查出全部总数，默认 ``False``。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    start_num: int = Field(1, alias='startNum')
    stop_num: int = Field(10, alias='stopNum')
    sort_infos: Optional[List[_SortInfo]] = Field(None, alias='sortInfos')
    return_total_count_flag: bool = Field(False, alias='returnTotalCountFlag')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名，过滤 None sortInfos）。"""
        payload: Dict[str, Any] = {
            'startNum': self.start_num,
            'stopNum': self.stop_num,
            'returnTotalCountFlag': self.return_total_count_flag,
        }
        if self.sort_infos:
            payload['sortInfos'] = [s.to_payload() for s in self.sort_infos]
        return payload


class _Thumbnail(BaseModel):
    """缩略图子结构（``thumbnailList[]`` 数组项）。

    Attributes:
        style: 图片大小：``Small`` / ``Big`` / ``Middle`` / ``Large``。
        url: 图片 url 地址。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    style: str = Field('', alias='style')
    url: str = Field('', alias='url')


class StorySearchItem(BaseModel):
    """搜索结果项（``data[]`` 数组项）。

    对应接口响应 ``data`` flat 数组中每一项的真实字段：
    ``storyId`` / ``storyName`` / ``userId`` / ``createdAt`` / ``updatedAt`` /
    ``coverFileId``，以及回忆故事行返回的扩展字段 ``description`` /
    ``storyType`` / ``thumbnailList`` / ``subtitle`` / ``albumType`` / ``driveId``。

    与列表接口的 ``AlbumListItem`` 字段名不同（列表用 ``id`` / ``name`` /
    ``cover``，搜索用 ``storyId`` / ``storyName`` / ``coverFileId``），故
    本接口独定义，不与 ``AlbumListItem`` 共用。

    Attributes:
        story_id: 故事/相册 id。
        story_name: 故事/相册名称。
        user_id: 用户 ID。
        created_at: 创建时间，如 ``2019-08-20T06:51:27.292Z`` 或
            ``20260702051527``（后端两种格式都可能出现）。
        updated_at: 修改时间。
        cover_file_id: 封面 id（后端可能返回字符串 ``"null"``）。
        description: 描述。
        story_type: 行类别（回忆故事行返回）：现网实测 ``1`` 个人云相册行 /
            ``2`` 回忆故事行（官方文档写作照片故事/推荐故事，与现网不符）。
        thumbnail_list: 缩略图地址列表。
        subtitle: 副标题（回忆故事行返回）。
        album_type: 相册类型（回忆故事行返回）：``1`` AI 生成；``2`` 用户制作。
        drive_id: 空间 Id。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    story_id: str = Field('', alias='storyId')
    story_name: str = Field('', alias='storyName')
    user_id: str = Field('', alias='userId')
    created_at: str = Field('', alias='createdAt')
    updated_at: str = Field('', alias='updatedAt')
    cover_file_id: str = Field('', alias='coverFileId')
    description: str = Field('', alias='description')
    story_type: str = Field('', alias='storyType')
    thumbnail_list: List[_Thumbnail] = Field(default_factory=list, alias='thumbnailList')
    subtitle: str = Field('', alias='subtitle')
    album_type: str = Field('', alias='albumType')
    drive_id: str = Field('', alias='driveId')


class SearchAIStoryRequest(BaseModel):
    """相册智能搜索接口入参。

    本接口属于 cloudId 体系（参数为 ``conditions`` / ``showInfo``），与
    媒体发送型同步基类 ``SyncRequest``（sendType/fileUrl/fileId/imageExt/
    sourceTaskId）字段不重合，故直接继承 ``BaseModel``，避免引入无关字段污染。

    Attributes:
        conditions: 搜索条件（必填），含 ``type``（0/2）与 ``keywords``。
        show_info: 分页和排序信息（``startNum`` / ``stopNum`` 闭区间从 1
            开始，``sortInfos`` / ``returnTotalCountFlag`` 嵌套在 ``showInfo`` 内）。
    """

    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    conditions: _Conditions = Field(..., alias='conditions')
    show_info: _ShowInfo = Field(default_factory=_ShowInfo, alias='showInfo')

    def to_payload(self) -> Dict[str, Any]:
        """输出接口文档要求的 payload（驼峰字段名）。

        - ``conditions`` 嵌套对象用子模型的 ``to_payload``。
        - ``showInfo`` 嵌套对象用子模型的 ``to_payload``（含 ``sortInfos`` /
          ``returnTotalCountFlag``）。
        """
        return {
            'conditions': self.conditions.to_payload(),
            'showInfo': self.show_info.to_payload(),
        }


class SearchAIStoryResponse(SyncResponse):
    """相册智能搜索接口出参（同步返回，F2 特殊信封）。

    扩展字段对应响应顶层业务字段：
      - ``total_rows``：命中的总数（``totalRows``）。
      - ``count``：当前返回数量（``count``）。
      - ``list``：故事/相册列表，每项为 ``StorySearchItem``（``data`` flat
        数组反序列化而来）。

    基类 ``SyncResponse.from_response`` 默认展平 ``data`` 嵌套层，但本接口
    ``data`` 是 flat 数组（不是对象），展平逻辑不适用，故必须重写
    ``from_response`` 手动解析。
    """

    model_config = ConfigDict(populate_by_name=True, extra='ignore')

    total_rows: int = Field(0, alias='totalRows')
    count: int = Field(0, alias='count')
    list: List[StorySearchItem] = Field(default_factory=list, alias='list')

    @classmethod
    def from_response(
        cls, raw: Dict[str, Any], trace_id: str = ''
    ) -> 'SearchAIStoryResponse':
        """从原始响应构造（F2 特殊信封）。

        处理逻辑：
          - ``code`` 是 int 0 表示成功（不是字符串 ``'0000'``）。
          - ``data`` 是 flat 数组（不是对象），直接是故事/相册列表。
          - ``totalRows`` / ``count`` 在顶层（不在 ``data`` 内）。
          - ``message`` 字段后端可能返回 ``msg``，做兼容。
        """
        code = raw.get('code')
        success = (code == 0)
        data_list = raw.get('data') or []
        if not isinstance(data_list, list):
            data_list = []
        items = [StorySearchItem.model_validate(item) for item in data_list]
        instance = cls(
            success=success,
            code=str(code) if code is not None else '',
            message=raw.get('message', '') or raw.get('msg', ''),
            data=data_list,
            total_rows=raw.get('totalRows', 0) or 0,
            count=raw.get('count', 0) or 0,
            list=items,
        )
        object.__setattr__(instance, 'raw', raw)
        return instance


@album_api_registry.register('search_ai_story')
class SearchAIStoryApi(BaseSyncApi):
    """相册智能搜索的同步 API（特殊桶 F2）。

    路径 ``POST /richlifeApp/search/SearchAIStory``，请求即返回最终结果
    （``data`` flat 数组 + ``totalRows`` / ``count`` 顶层），无 ``taskId`` 轮询。

    Response 字段扩展了 ``total_rows`` / ``count`` / ``list``，且响应信封
    与基类 ``SyncResponse`` 不一致（``code`` 是 int 0、``data`` 是 flat 数组、
    ``totalRows`` / ``count`` 在顶层），故必须类型化 ``execute`` 签名 + 重写
    ``_parse_response`` 指向 ``SearchAIStoryResponse``。
    """

    PATH = '/richlifeApp/search/SearchAIStory'

    api_category = 'album'
    api_label = '搜索 AI 故事相册'

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
        request: SearchAIStoryRequest,
        *args: Any,
        info_dict: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SearchAIStoryResponse:
        """类型化入口：入参指向 ``SearchAIStoryRequest``，返回
        ``SearchAIStoryResponse``。

        本接口 Request 为 cloudId 体系（非 ``SyncRequest`` 子类）、Response
        字段扩展且信封特殊（F2），均与基类不一致，故必须类型化覆盖 execute
        签名。实际流程通过 ``super().execute`` 转发，响应类型转换由重写的
        ``_parse_response`` 完成。
        """
        return super().execute(request, *args, info_dict=info_dict, **kwargs)

    def _parse_response(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> SearchAIStoryResponse:
        """重写基类钩子：用 ``SearchAIStoryResponse.from_response`` 构造响应。

        基类 ``BaseSyncApi._parse_response`` 硬编码用 ``SyncResponse.from_response``
        构造基类实例，无法识别本接口扩展字段（``total_rows`` / ``count`` /
        ``list``）及 F2 特殊信封（``code`` 是 int 0、``data`` 是 flat 数组）。
        本方法改用子类的 ``from_response``，其内部手动解析 F2 信封。
        """
        return SearchAIStoryResponse.from_response(raw, trace_id)
