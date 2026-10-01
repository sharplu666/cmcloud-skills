#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""album 子包专用鉴权头构造器。

对齐旧版相册 HTTP 封装的 ``_get_header``
与 ``_send_request(header_type=...)`` 模式：相册类接口在标准云盘鉴权头
（``mclaw.api.auth.get_auth_header``）基础上，按接口类型追加额外字段。

提供三个函数：
  - ``get_album_header``：标准相册鉴权头
      在 ``get_auth_header()`` 返回的 6 个标准字段基础上追加：
        * ``Content-Type: application/json``
        * ``x-yun-client-info``（设备指纹）
      对齐 legacy ``SkillAuthConfig.get_album_header``（cm_cloud_auth.py:150-154）。

  - ``get_album_share_header``：分享类相册鉴权头
      在 ``get_album_header`` 基础上再追加：
        * ``x-DeviceInfo``（分享端点校验更严，需额外设备信息）
      对齐 legacy ``SkillAuthConfig.get_album_share_header``
      （cm_cloud_auth.py:156-159）。

  - ``get_album_multipart_header``：multipart 表单提交用相册鉴权头
      标准云盘鉴权头 + ``x-yun-client-info``，**不设** ``Content-Type``
      （由 requests 生成含 boundary 的头，预设会丢失边界）。

设计要点：
  - **每次调用都实时读取 ``.env``**：两个函数内部都调 ``get_auth_header()``
    （经 ``get_skill_auth()`` → ``_build_skill_auth_config()`` →
    ``_read_env_values()``），token 文件或 .env 更新后下次请求即生效。
  - **每次返回新 dict**：``get_auth_header()`` 链路每次返回新对象，本层
    在其基础上 ``h[key] = value`` 修改不污染原 dict。
  - **不依赖 ``SkillAuthConfig`` 子类扩展**：通过函数组合而非类继承实现，
    避免 ``mclaw.api.auth.SkillAuthConfig`` 与 legacy ``cm_cloud_auth`` 的
    ``get_album_header`` / ``get_album_share_header`` 方法重复定义。

使用方式（在叶子 Api 子类的 ``__init__`` 中覆盖 ``self._auth``）：

    from mclaw.api.album._get_auth import get_album_share_header

    class AlbumShareGetInfoApi(BaseSyncApi):
        def __init__(self, host, auth_fn, logger=None, redact_params=None):
            super().__init__(host, auth_fn, logger, redact_params)
            # 覆盖为 share 端点专用鉴权头
            self._auth = get_album_share_header
"""

from __future__ import annotations

from typing import Dict

from mclaw.api.auth import get_auth_header


__all__ = ['get_album_header', 'get_album_share_header', 'get_album_multipart_header']


#: 设备指纹常量。对齐 ``cm_cloud_auth.py:16`` 的 ``X_YUN_CLIENT_INFO``，
#: 服务端用于设备识别与风控。如需多端差异化，调整为按 .env 读取即可。
X_YUN_CLIENT_INFO: str = (
    '||36|2.7.7||Nexus 5|10ff6362-b90c-4dc0-86bb-6b95d130cc4a'
    '||android 6.0|||||'
)


def get_album_header() -> Dict[str, str]:
    """标准相册鉴权头。

    在 ``get_auth_header()`` 返回的标准云盘鉴权头（AppId / AppKey / SecretKey /
    accessToken / deviceid / channelid）基础上追加：
      - ``Content-Type: application/json``
      - ``x-yun-client-info``（设备指纹）

    对齐 legacy ``cm_cloud_auth.py:SkillAuthConfig.get_album_header`` (lines 150-154)。
    每次调用都通过 ``get_auth_header()`` 实时读取 ``.env``，token 文件更新后
    下次请求即生效。
    """
    h = get_auth_header()
    h['Content-Type'] = 'application/json'
    h['x-yun-client-info'] = X_YUN_CLIENT_INFO
    return h


def get_album_share_header() -> Dict[str, str]:
    """分享类相册鉴权头。

    在 ``get_album_header()`` 基础上追加 ``x-DeviceInfo``（分享端点校验更严，
    需额外设备信息字段）。

    对齐 legacy ``cm_cloud_auth.py:SkillAuthConfig.get_album_share_header``
    (lines 156-159)。每次调用都通过 ``get_album_header()`` →
    ``get_auth_header()`` 实时读取 ``.env``，token 文件更新后下次请求即生效。
    """
    h = get_album_header()
    h['x-DeviceInfo'] = X_YUN_CLIENT_INFO
    return h


def get_album_multipart_header() -> Dict[str, str]:
    """multipart 表单提交用的相册鉴权头。

    标准云盘鉴权头 + ``x-yun-client-info``，**不设** ``Content-Type``——
    multipart 请求头由 requests 自动生成（含 boundary），预设会丢失边界。

    每次调用都通过 ``get_auth_header()`` 实时读取 ``.env``，token 文件更新后
    下次请求即生效。
    """
    h = get_auth_header()
    h['x-yun-client-info'] = X_YUN_CLIENT_INFO
    return h
