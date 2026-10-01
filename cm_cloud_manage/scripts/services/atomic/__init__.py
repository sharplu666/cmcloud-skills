#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原子能力层 —— 单 API 域封装（client 为聚合出口，其余为各域实现）。

依赖方向：编排层（organize/refine/search_fetch/play_media）与 CLI 显式 import
本包具体模块路径；本包内禁止 import 编排层与 stdout_receipt。
"""
