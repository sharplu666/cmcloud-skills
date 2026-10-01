#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_fusion 共享 BaseModel（Pydantic v2）。

被 `search_merge_file_api.py` 与 `search_merge_image_api.py` 复用的入参/出参
子结构。本模块**不定义 Request/Response/Api 子类**，只放业务结构 BaseModel。

Pydantic v2 化收益：
  - snake_case 字段名 + camelCase alias，调用方既能 `order_by='takenAt'` 也能
    `orderBy='takenAt'` 构造
  - 嵌套结构自动递归校验，无需手写 from_dict 循环
  - 序列化统一走 `model_dump(by_alias=True, exclude_none=True)`
  - 类型错（如 bool 字段传 str）构造时即抛 ValidationError

字段命名：Python 用 snake_case，`Field(alias=...)` 映射 API 驼峰字段名。
服务端拼写错误也保留 alias（如 `filed` / `FileSizeRage`），不修正。

字段必填性：
  - M（必填）：`Field(..., alias=...)`，无默认值，构造时必须提供
  - O（可选）：`Optional[T] = Field(None, alias=...)`，缺失时为 None
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


__all__ = [
    # 入参子结构
    'SortRange',
    'FileTimeRange',
    'FileSizeRage',
    'MergePageInfo',
    'SearchFileParamV3',
    'SearchFileDynamicParam',
    'SelectFaceItem',
    'FaceRecognizeSelectFaceItem',
    'RecognizeFaceInfo',
    # 出参子结构
    'FaceInfo',
    'LabelInfo',
    'ImageQuality',
    'AiAnalysisInfo',
    'MediaMetaInfo',
    'MediaPreviewInfo',
    'AddressDetail',
    'LocationAoi',
    'ThumbnailInfo',
    'Tag',
    'File',
    'AmbiguityReason',
    'AmbiguityItem',
    # 助手
    'apply_ai_score_defaults',
]


# 公共 ConfigDict：populate_by_name + 忽略服务端新增字段
_MODEL_CONFIG = ConfigDict(populate_by_name=True, extra='ignore')


# ──────────────────────────── 入参子结构 ────────────────────────────


class SortRange(BaseModel):
    """排序字段。"""

    model_config = _MODEL_CONFIG

    order_by: str = Field(..., alias='orderBy')
    order_direction: bool = Field(..., alias='orderDirection')  # true 降序，false 升序


class FileTimeRange(BaseModel):
    """搜索时间范围。"""

    model_config = _MODEL_CONFIG

    start_at: Optional[str] = Field(None, alias='startAt')
    end_at: Optional[str] = Field(None, alias='endAt')
    # 服务端响应原样拼写为 filed（非 field），alias 保留
    filed: Optional[str] = None


class FileSizeRage(BaseModel):
    """文件大小范围（单位 byte）。

    类名保留服务端原样拼写 FileSizeRage（非 Range）。
    """

    model_config = _MODEL_CONFIG

    start_size: int = Field(..., alias='startSize')
    end_size: int = Field(..., alias='endSize')


class MergePageInfo(BaseModel):
    """通用分页信息。"""

    model_config = _MODEL_CONFIG

    page_size: Optional[int] = Field(None, alias='pageSize')
    page_after: Optional[List[Any]] = Field(None, alias='pageAfter')
    sort_infos: Optional[List[SortRange]] = Field(None, alias='sortInfos')
    need_total_count: Optional[int] = Field(None, alias='needTotalCount')  # 0 不返回，1 返回


class SearchFileParamV3(BaseModel):
    """个人云搜文件/搜图共用条件（searchType=File / ImageFile 时使用）。"""

    model_config = _MODEL_CONFIG

    type_list: Optional[List[int]] = Field(None, alias='typeList')
    name_list: Optional[List[str]] = Field(None, alias='nameList')
    address_list: Optional[List[str]] = Field(None, alias='addressList')
    thing_list: Optional[List[str]] = Field(None, alias='thingList')
    doc_type_list: Optional[List[str]] = Field(None, alias='docTypeList')
    suffix_list: Optional[List[str]] = Field(None, alias='suffixList')
    time_list: Optional[List[FileTimeRange]] = Field(None, alias='timeList')
    enable_intelligent: Optional[bool] = Field(None, alias='enableIntelligent')
    enable_full_text_search: Optional[bool] = Field(None, alias='enableFullTextSearch')
    intelligent_type: Optional[str] = Field(None, alias='intelligentType')
    include_file_id_list: Optional[List[str]] = Field(None, alias='includeFileIdList')
    exclude_file_id_list: Optional[List[str]] = Field(None, alias='excludeFileIdList')
    recursion: Optional[bool] = None
    size_range: Optional[FileSizeRage] = Field(None, alias='sizeRange')


class SearchFileDynamicParam(BaseModel):
    """个人动态搜文件/搜图共用条件（searchType=FileDynamic / ImageDynamic 时使用）。"""

    model_config = _MODEL_CONFIG

    start_time: str = Field(..., alias='startTime')
    end_time: str = Field(..., alias='endTime')
    keyword: str = Field(...)
    dynamic_type: int = Field(..., alias='dynamicType')  # 1 查看动态，2 上传动态
    content_type: Optional[int] = Field(None, alias='contentType')  # 1 图片，2 音频，3 视频，4 其他文件


class SelectFaceItem(BaseModel):
    """图文搜人选择人脸（用户在参考图上勾选的人脸框）。

    searchType=SemanticImagePerson 时，``searchImagePersonParam.selectFaceList`` 元素。
    """

    model_config = _MODEL_CONFIG

    file_id: str = Field(..., alias='fileId')
    face_info: List[FaceInfo] = Field(..., alias='faceInfo')


class FaceRecognizeSelectFaceItem(BaseModel):
    """人脸识别结果中的筛选/选择人脸项（``RecognizeFaceInfo.selectFaceList`` 元素）。"""

    model_config = _MODEL_CONFIG

    file_id: Optional[str] = Field(None, alias='fileId')
    exclude: Optional[bool] = None
    label: Optional[str] = None


class RecognizeFaceInfo(BaseModel):
    """人脸识别的图片理解结果（rewriteQuery + 筛选/选择后的人脸列表）。

    ``face/recognize`` 无歧义时返回；二次调用 ``merge/image`` 时随
    ``searchImagePersonParam.recognizeFaceInfo`` 原样回传（配合 skipMultimodal=true）。
    """

    model_config = _MODEL_CONFIG

    rewrite_query: Optional[str] = Field(None, alias='rewriteQuery')
    select_face_list: Optional[List[FaceRecognizeSelectFaceItem]] = Field(
        None, alias='selectFaceList'
    )


# ──────────────────────────── 出参子结构 ────────────────────────────


class FaceInfo(BaseModel):
    """人脸信息。"""

    model_config = _MODEL_CONFIG

    x0: float = Field(...)
    y0: float = Field(...)
    x1: float = Field(...)
    y1: float = Field(...)
    score: Optional[float] = None
    face_quality: Optional[float] = Field(None, alias='faceQuality')
    # 图文搜人选脸二次搜索：用户点选第几个人脸的顺序，从 1 开始全局递增（跨 fileId 不重置）
    index: Optional[int] = None


class LabelInfo(BaseModel):
    """标签信息。"""

    model_config = _MODEL_CONFIG

    name: str = Field(...)
    score: Optional[float] = None


class ImageQuality(BaseModel):
    """图片质量评分。

    ``imgQuality`` 在 ``merge/image`` 响应中可能缺失（``imageQuality`` 为空对象）；
    字段声明为 Optional，避免嵌套校验导致整批 ``fileList`` 解析失败。
    """

    model_config = _MODEL_CONFIG

    img_quality: Optional[float] = Field(None, alias='imgQuality')


class AiAnalysisInfo(BaseModel):
    """AI 分析信息（仅个人云图片类整合搜索接口返回）。"""

    model_config = _MODEL_CONFIG

    face_info_list: List[FaceInfo] = Field(default_factory=list, alias='faceInfoList')
    thing_label_list: List[LabelInfo] = Field(default_factory=list, alias='thingLabelList')
    image_quality: Optional[ImageQuality] = Field(None, alias='imageQuality')
    score: Optional[float] = None
    people_name_list: List[str] = Field(default_factory=list, alias='peopleNameList')
    relationship_name_list: List[str] = Field(default_factory=list, alias='relationshipNameList')
    content: Optional[str] = None
    object_list: List[str] = Field(default_factory=list, alias='objectList')
    img_ocr_content: Optional[str] = Field(None, alias='imgOCRContent')


def _normalize_duration_input(raw: Any) -> Optional[str]:
    """duration 入模前预处理：API 与 manage normalize 可能返回 int/float，统一转 str。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (int, float)):
        return str(raw)
    return str(raw)


class MediaMetaInfo(BaseModel):
    """媒体元信息。"""

    model_config = _MODEL_CONFIG

    duration: Annotated[
        Optional[str],
        BeforeValidator(_normalize_duration_input),
    ] = None
    width: Optional[int] = None
    height: Optional[int] = None
    taken_at: Optional[str] = Field(None, alias='takenAt')
    live_photo: Optional[bool] = Field(None, alias='livePhoto')
    make: Optional[str] = None
    model: Optional[str] = None


class MediaPreviewInfo(BaseModel):
    """媒体预览信息。"""

    model_config = _MODEL_CONFIG

    status: int = Field(...)  # 转码状态，详见 TranscodingStatus
    url: Optional[str] = None


class LocationAoi(BaseModel):
    """AOI 结构化信息（AddressDetail.locationAoi 元素）。"""

    model_config = _MODEL_CONFIG

    name: str = Field(...)  # AOI 名称
    sub_type: Optional[str] = Field(None, alias='subType')  # 分类编码（高德中类数字编码）
    sub_type_name: Optional[str] = Field(None, alias='subTypeName')  # 分类名称（编码对应的中文描述）
    area: Optional[str] = None  # 面积（平方米）


class AddressDetail(BaseModel):
    """地理位置信息。"""

    model_config = _MODEL_CONFIG

    addressline: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    township: Optional[str] = None
    longitude: Optional[str] = None  # 经度，小数点后 6 位，负值西经
    latitude: Optional[str] = None  # 纬度，小数点后 6 位，负值南纬
    altitude: Optional[str] = None  # 海拔高度，单位米
    location_aoi: Optional[List[LocationAoi]] = Field(None, alias='locationAoi')  # AOI 结构化信息列表
    location_names: Optional[List[str]] = Field(None, alias='locationNames')  # 景点地点名称（逗号拆分的旧格式名称列表）


class ThumbnailInfo(BaseModel):
    """缩略图信息（File.thumbnailUrls 元素）。"""

    model_config = _MODEL_CONFIG

    style: str = Field(...)  # Small(128) / Middle(480) / Big(800) / Large(1080)
    url: Optional[str] = None  # 对应尺寸缩略图生成失败时为空


def _normalize_user_tags_input(raw: Any) -> Any:
    """userTags 入模前预处理：保留 key 非空项，value 缺省补 ''。"""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return raw
    items: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get('key') or '').strip()
        if not key:
            continue
        normalized = dict(entry)
        normalized['key'] = key
        normalized.setdefault('value', '')
        items.append(normalized)
    return items or None


class Tag(BaseModel):
    """用户自定义标签（File.userTags 元素，key/value 键值对）。"""

    model_config = _MODEL_CONFIG

    key: str = Field(...)
    value: str = Field('')


class File(BaseModel):
    """搜索返回的文件信息。

    ``type=folder`` 时服务端常省略 ``size``、``contentHash``、``contentHashAlgorithm``，
    模型层以 ``0`` / ``''`` 作为缺省值。

    动态搜索（FileDynamic/ImageDynamic）翻页时，后端可能返回仅含 ``fileId`` 的残缺条目
    （已删除/不可访问），故 ``parent_file_id`` / ``name`` / ``type`` / ``category`` /
    ``created_at`` 也放宽为可选并给默认值，避免单条脏数据让整批 ``fileList`` 解析失败。
    与 ``cm_cloud_organize/scripts/file_model.File``（dataclass 版，全字段降级默认值）行为对齐。
    """

    model_config = _MODEL_CONFIG

    file_id: str = Field(..., alias='fileId')
    parent_file_id: str = Field('', alias='parentFileId')
    name: str = ''
    content: Optional[str] = None
    name_path: Optional[str] = Field(None, alias='namePath')
    type: str = Field('file')  # file / folder
    category: str = Field('others')
    created_at: str = Field('', alias='createdAt')
    updated_at: Optional[str] = Field(None, alias='updatedAt')
    local_created_at: Optional[str] = Field(None, alias='localCreatedAt')
    local_updated_at: Optional[str] = Field(None, alias='localUpdatedAt')
    size: int = 0
    file_extension: Optional[str] = Field(None, alias='fileExtension')
    thumbnail_url: Optional[str] = Field(None, alias='thumbnailUrl')
    thumbnail_urls: Optional[List[ThumbnailInfo]] = Field(None, alias='thumbnailUrls')
    content_hash: str = Field('', alias='contentHash')
    content_hash_algorithm: str = Field('', alias='contentHashAlgorithm')
    media_meta_info: Optional[MediaMetaInfo] = Field(None, alias='mediaMetaInfo')
    address_detail: Optional[AddressDetail] = Field(None, alias='addressDetail')
    starred: Optional[bool] = None
    media_preview_info: Optional[MediaPreviewInfo] = Field(None, alias='mediaPreviewInfo')
    ai_analysis_info: Optional[AiAnalysisInfo] = Field(None, alias='aiAnalysisInfo')
    user_tags: Annotated[
        Optional[List[Tag]],
        BeforeValidator(_normalize_user_tags_input),
    ] = Field(None, alias='userTags')


def apply_ai_score_defaults(files: List[File], default_score: float) -> List[File]:
    """为 image 类 File 补 ``aiAnalysisInfo.score`` 默认值（fill-if-missing）。

    仅 ``category == 'image'`` 参与：``ai_analysis_info`` 缺失时构造仅含
    ``score`` 的 ``AiAnalysisInfo``；``score`` 已有值则保留原值。其余 category
    不动。原地修改并原样返回列表，供各搜索 API 的 ``_build_result`` 统一调用
    ——默认值随 File.model_dump 落进 search.jsonl，喂给 AI 选图 imageIdFile。
    """
    for file_ in files:
        if file_.category != 'image':
            continue
        info = file_.ai_analysis_info
        if info is None:
            file_.ai_analysis_info = AiAnalysisInfo(score=default_score)
        elif info.score is None:
            info.score = default_score
    return files


class AmbiguityReason(BaseModel):
    """图文搜人歧义原因（searchType=SemanticImagePerson 且歧义时返回）。

    ``reasonText`` 描述当前歧义情况，``selectText`` 引导用户在参考图上选择人脸。
    """

    model_config = _MODEL_CONFIG

    reason_text: str = Field(default='', alias='reasonText')
    select_text: str = Field(default='', alias='selectText')


class AmbiguityItem(BaseModel):
    """图文搜人歧义项（searchType=SemanticImagePerson 且歧义时返回）。

    响应 ``ambiguityList`` 元素。``ambiguityFlag=true`` 表示需要用户在参考图上选脸。
    """

    model_config = _MODEL_CONFIG

    file_id: str = Field(..., alias='fileId')
    ambiguity_flag: bool = Field(..., alias='ambiguityFlag')  # true=需用户选脸
    reason: AmbiguityReason = Field(default_factory=AmbiguityReason, alias='reason')
    # 图片中识别到的人脸坐标列表
    face_info_list: List[FaceInfo] = Field(default_factory=list, alias='faceInfoList')
