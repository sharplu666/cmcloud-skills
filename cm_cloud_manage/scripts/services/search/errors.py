#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search 子包业务异常类型。"""

from __future__ import annotations

from typing import List

from services.errors import OperationServiceError


class SearchServiceError(OperationServiceError):
    """检索业务失败（参数构建/服务端返回失败/落盘失败等）。

    继承 manage ``OperationServiceError``：cli 命令模块的统一异常梯可直接用
    ``OperationServiceError`` 档接住本类（无需单独一档）。

    ``message`` 即面向 agent 的回执 message：自然语言中文，含原因与下一步行动，
    不含数字退出码 / 错误码枚举。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = str(message)


class NonFolderScopeIds(SearchServiceError):
    """``--scope-in``/``--scope-out`` 传入了非文件夹 fileId：整体拒绝。

    ``file_ids`` 为类型不为 folder 的 id 列表（含 batchGet 查不到的 id），
    ``label`` 为 ``'--scope-in'``/``'--scope-out'``；由 cli 层组拒绝回执与
    ``next.search-by-ids`` 指路。
    """

    def __init__(self, message: str, file_ids: List[str], label: str) -> None:
        super().__init__(message)
        self.file_ids = list(file_ids)
        self.label = label


__all__ = ['SearchServiceError', 'NonFolderScopeIds']
