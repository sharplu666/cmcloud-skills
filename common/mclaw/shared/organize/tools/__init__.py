#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.shared.organize.tools —— 整理（organize）IO 工具共享层。

与 ``bucket`` / ``selector`` 同级，承载「搜索结果 ``List[File]`` 的 JSONL 落盘与读回」
能力，供换 bucket 维度时复用已落盘的全量搜索结果，避免重翻页。

设计：
  - 输入 ``File`` 来自 ``mclaw.api.search_fusion``（Pydantic v2 BaseModel，
    snake_case 字段 + camelCase alias）
  - 不发 HTTP、不持鉴权；纯本地文件 IO
  - 不依赖任何 skill 私有结构 / settings / 环境变量；落盘位置由调用方显式传入
    （``output_path`` 或 ``output_dir``）
"""

from mclaw.shared.organize.tools.search_results_io import (  # noqa: F401
    SearchResultsHeader,
    load_search_results,
    save_search_results,
    write_search_results_file,
)

__all__ = [
    'SearchResultsHeader',
    'load_search_results',
    'save_search_results',
    'write_search_results_file',
]
