#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""image_tools —— AI 图片处理 skill 的共享业务编排层。

从各 ``dev/skills/image_tool/*/scripts/`` 下提取的跨 skill 复用逻辑：
  - ``ai_space.move_result_to_ai_space``：结果文件归档到 AI 空间（按 session 解析目录）
  - ``ai_space.move_result_to_directory``：结果文件移动到调用方指定目录（按 fileId）
  - ``ai_space.resolve_session_from_env``：从环境变量读取并 normalize session（与 submit.py 同款）
  - ``ai_space.ensure_session_default_dir``：按会话创建默认保存目录（ensure，非仅查看）
  - ``ai_space.ensure_session_query_dir``：在对话文件/我的任务下按 query 创建结果保存目录
  - ``utils.handle_sub_result_output``：轮询结果输出处理
  - ``utils.extract_poll_result``：从轮询响应提取状态与 fileUrlList
  - ``utils.emit_file_path_list_card`` / ``utils.emit_big_image_list_card``：渲染卡直出
  - ``utils.build_url`` / ``utils.generate_source_task_id``：纯工具函数

设计原则：
  - 本包**不发 HTTP、不持鉴权/host**。所有 HTTP 调用通过调用方注入的
    ``dispatcher: ApiDispatcher`` 完成（属性链 ``d.<namespace>.<leaf>(req)``）。
  - 调用方负责构造 dispatcher（``ApiDispatcher(host=HOST, auth_fn=get_auth_header)``）。
"""

from mclaw.shared.image_tools.ai_space import (
    ensure_session_default_dir,
    ensure_session_query_dir,
    move_result_to_ai_space,
    move_result_to_directory,
    resolve_session_from_env,
)
from mclaw.shared.image_tools.utils import (
    TASK_STATUS_TEXT,
    build_url,
    emit_big_image_list_card,
    emit_file_path_list_card,
    extract_poll_result,
    generate_source_task_id,
    handle_sub_result_output,
)

__all__ = [
    'move_result_to_ai_space',
    'move_result_to_directory',
    'resolve_session_from_env',
    'ensure_session_default_dir',
    'ensure_session_query_dir',
    'handle_sub_result_output',
    'extract_poll_result',
    'build_url',
    'generate_source_task_id',
    'TASK_STATUS_TEXT',
    'emit_file_path_list_card',
    'emit_big_image_list_card',
]
