#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.shared.postprocess —— 云盘 CLI 共用后处理（纯函数为主）。

子模块职责：

- ``paths`` / ``merge_normalize`` / ``search_param`` / ``cli_rows``：纯函数，无 HTTP
- ``api_obs``：可观测性收尾（依赖 common_auth 的 cli_timing / cli_trace）

请按需显式导入子模块，例如::

    from mclaw.shared.postprocess.paths import normalize_cloud_dir_path
    from mclaw.shared.postprocess.merge_normalize import merge_file_row_normalize
    from mclaw.shared.cm_cloud.folder_ops import ensure_mclaw_dir_path
"""
