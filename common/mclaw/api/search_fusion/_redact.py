#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_fusion 搜索接口日志脱敏/截断工具。

服务端返回的 ``fileList`` 含冗长/敏感字段（如 ``thumbnailUrl(s)`` 长达数百字符的
签名 URL、``contentHash``、``aiAnalysisInfo.content`` 整段 AI 描述），完整打印
会污染日志。本模块提供 ``redact_search_result``，构造一份适合日志输出的精简副本：

  - 移除：``thumbnailUrl`` / ``thumbnailUrls`` / ``contentHash`` / ``contentHashAlgorithm``
  - 截断：``aiAnalysisInfo.content`` 保留前 10 字符 + ``...``
  - 截断：顶层 ``semanticInfo`` 保留前 5 字符 + ``...``（仅语义搜图返回）
  - 追加：顶层 ``custom_num`` = 本次返回的 fileId 个数（``len(fileList)``，
    缺失/空为 0），方便日志一眼读数

**仅作用于日志展示**，原始 ``response.raw`` / ``response.file_list`` 不受影响。
返回新 dict（不可变模式），不修改入参。
"""

from __future__ import annotations

from typing import Any, Dict


__all__ = ['redact_search_result', 'strip_keywords_tag']


# 每个 File 上需要整字段移除的 key（位于 fileList[] 顶层）
_REDACT_FILE_KEYS = ('thumbnailUrl', 'thumbnailUrls', 'contentHash', 'contentHashAlgorithm')

# aiAnalysisInfo.content 保留前 N 字符
_CONTENT_KEEP = 10
_CONTENT_SUFFIX = '...'

# 顶层 semanticInfo（语义搜图返回）保留前 N 字符
_SEMANTIC_INFO_KEEP = 5
_SEMANTIC_INFO_SUFFIX = '...'


def redact_search_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """构造搜索接口日志友好的 result dict。

    遍历 ``raw['data']['fileList']``，对每个 File：
      - 删除 ``_REDACT_FILE_KEYS`` 中的字段
      - ``aiAnalysisInfo.content`` 超过 ``_CONTENT_KEEP`` 字符时截断并加 ``...``

    其余字段（含 ``fileId`` / ``name`` / ``size`` / ``aiAnalysisInfo`` 其它子字段
    等）原样保留。返回新 dict，入参 ``raw`` 不被修改。

    Args:
        raw: 原始响应 dict（通常是 ``response.raw``）。

    Returns:
        与 ``raw`` 同构的精简副本；若结构不符（无 fileList）则原样返回。
    """
    if not isinstance(raw, dict):
        return raw

    data = raw.get('data')
    if not isinstance(data, dict):
        return {**raw, 'custom_num': 0}

    file_list = data.get('fileList')
    if not isinstance(file_list, list) or not file_list:
        return {**raw, 'custom_num': 0}

    redacted_files = []
    for f in file_list:
        if not isinstance(f, dict):
            redacted_files.append(f)
            continue
        # 浅拷贝并剔除需脱敏的顶层字段
        rf = {k: v for k, v in f.items() if k not in _REDACT_FILE_KEYS}
        # content 截断：构造新 aiAnalysisInfo，不改原对象
        ai = rf.get('aiAnalysisInfo')
        if isinstance(ai, dict):
            c = ai.get('content')
            if isinstance(c, str) and len(c) > _CONTENT_KEEP:
                rf['aiAnalysisInfo'] = {
                    **ai,
                    'content': c[:_CONTENT_KEEP] + _CONTENT_SUFFIX,
                }
        redacted_files.append(rf)

    # 不可变：浅拷贝外壳，只替换 fileList
    new_data = {**data, 'fileList': redacted_files}
    # semanticInfo 截断（仅语义搜图路径会返回，位于 data 顶层）
    si = new_data.get('semanticInfo')
    if isinstance(si, str) and len(si) > _SEMANTIC_INFO_KEEP:
        new_data = {**new_data, 'semanticInfo': si[:_SEMANTIC_INFO_KEEP] + _SEMANTIC_INFO_SUFFIX}
    # custom_num：本次搜索返回的 fileId 个数（= len(fileList)），仅供日志阅读
    return {**raw, 'data': new_data, 'custom_num': len(file_list)}


# ──────────────────────────── keywordsTag 高亮标签清理 ────────────────────────────


# 后端在命中关键字的字段值上会包裹 <keywordsTag>...</keywordsTag> 高亮标签，
# 端侧约定去除后再呈现（参考 dev/docs/api/能开平台-MClaw新增接口.md）。
_KEYWORDS_TAG_OPEN = '<keywordsTag>'
_KEYWORDS_TAG_CLOSE = '</keywordsTag>'


def strip_keywords_tag(raw: Dict[str, Any]) -> Dict[str, Any]:
    """就地把 ``raw['data']['fileList']`` 每条 File 的 ``name`` 上的高亮标签剥除。

    后端搜索接口在命中关键字时会在 ``name`` 上自动包裹
    ``<keywordsTag>...</keywordsTag>`` 标签，端侧约定去除后再呈现
    （参考 ``dev/docs/api/能开平台-MClaw新增接口.md``）。本函数遍历
    ``fileList``，**仅清理每条 File 的 ``name`` 字段**，其余字段不动。

    在 ``_parse_response`` 阶段调用，确保解析出的 ``File`` 对象与
    ``response.raw`` 都拿到干净值。修改入参 ``raw`` 并返回（方便链式调用）。
    结构不符（无 data/fileList）时静默返回。

    Args:
        raw: 原始响应 dict。

    Returns:
        同一对象 ``raw``（已就地修改）。
    """
    if not isinstance(raw, dict):
        return raw

    data = raw.get('data')
    if not isinstance(data, dict):
        return raw

    file_list = data.get('fileList')
    if not isinstance(file_list, list):
        return raw

    for f in file_list:
        if not isinstance(f, dict):
            continue
        name = f.get('name')
        if isinstance(name, str) and name:
            f['name'] = name.replace(_KEYWORDS_TAG_CLOSE, '').replace(_KEYWORDS_TAG_OPEN, '')
    return raw
