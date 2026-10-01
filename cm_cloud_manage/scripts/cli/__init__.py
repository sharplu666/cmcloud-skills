#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子命令实现包 —— 每个 ``.py`` 对应一个 CLI 子命令（``run()`` 入口）。

此处统一 re-export 各子命令的 ``run`` 入口与 ``parse_*`` 辅助函数，
供 ``main.py`` 单点导入。
"""
from cli.batch_check_exists import parse_check_exists_specs, run as run_batch_check_exists
from cli.batch_copy import run as run_batch_copy
from cli.batch_get import run as run_batch_get
from cli.batch_move import run as run_batch_move
from cli.batch_rename import parse_batch_rename_spec, run as run_batch_rename
from cli.create_default_save_dir import run as run_create_default_save_dir
from cli.get_default_save_dir import run as run_get_default_save_dir
from cli.download import run as run_download
from cli.get_path import run as run_get_path
from cli.mkdir import run as run_mkdir
from cli.organize import run as run_organize
from cli.person_search import run as run_person_search
from cli.play_media import run as run_play_media
from cli.refine import run as run_refine
from cli.search import run as run_search
from cli.semantic_search import run as run_semantic_search
from cli.dynamic import run as run_dynamic
from cli.search_transfer import run as run_search_transfer
from cli.search_by_ids import run as run_search_by_ids
from cli.upload import run as run_upload
