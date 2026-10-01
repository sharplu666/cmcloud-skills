#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refine 子包：对 search.jsonl 去重/精选，产 dedup.jsonl/select.jsonl 子集。

去重/精选是独立能力（不再内嵌于 organize plan）：对 search 命令落盘的 search.jsonl
做变换，把存活文件及其 bucket 标签写回同一会话目录的子集 jsonl，供 ``organize plan
--from <handle>/<file>.jsonl`` 读取。subset 读写（``subset_io``）与编排（``steps``）
都在本子包内，**不 import ``services.organize.steps``**，避免 organize/common 循环耦合。
"""

from __future__ import annotations

__all__: list[str] = []
