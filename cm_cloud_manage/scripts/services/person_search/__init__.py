#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图文搜人（person-search）编排包。

入口 ``run_person_search``（flow）；校验在 ``args``、face/recognize 第一跳与
歧义判定在 ``recognize``、selectFaceList 歧义卡在 ``cards``。检索翻页/落盘/回执
复用 ``services/search`` 既有链路（fetch_loop + results_store + stdout_receipt）。
"""
