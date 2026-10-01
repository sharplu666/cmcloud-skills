#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search 子包：检索两命令（search / dynamic）的业务编排。

    - args.py           入参校验与规范化（validators / input_parse / constants 合一）
    - api_call.py       merge 搜索真实调用点（唯一网络出入口）
    - backup_scope.py   备份口径目录名 → 根目录 fileId 预设（search --backup-folder 用）
    - errors.py         SearchServiceError（manage OperationServiceError 子类）
    - param_build.py    五场景检索任务构建（场景路由 + 稳定参数快照）
    - fetch_loop.py     翻页编排主循环（view 单页 / full 全量断点续传）
    - media_enrich.py   audio/video 动态卡片的媒体富化（duration + contentSchedule）
    - results_store.py  search.jsonl 落盘（header + 断点指纹协议，与 organize/refine 续拉互通）
    - stdout_receipt.py 检索专属回执（searchResults 交接行 / 卡片 / agent_note）

进度行（progress_*）走 ``services.stdout_receipt`` 公共层；错误 / 让出的 meta 壳
在 cli 命令模块（cli/search.py、cli/dynamic.py）。
"""

from __future__ import annotations

__all__: list[str] = []
