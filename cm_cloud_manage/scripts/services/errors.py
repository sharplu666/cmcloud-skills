#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""services 层异常类型。

- ``CliValidationError``：cli 层入参校验失败，``message`` 即回执 message。
- ``OperationServiceError``：services 编排失败（业务失败、超限、路径越权等），
  message 为自然语言中文，直接写进 ``record=error`` 回执。
"""

from __future__ import annotations

from typing import Optional


class CliValidationError(Exception):
    """入参不合法；``message`` 即回执 message（自然语言修正提示）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = str(message)


class OperationServiceError(RuntimeError):
    """services 层编排失败；``message`` 直接写进回执。

    ``say`` 可选：面向用户的 sayToUser 文案（如需与 error.message 分离时使用）；
    缺省 None，回执 sayToUser 与 message 同文。
    """

    def __init__(self, message: str, say: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = str(message)
        self.say = say


def wrap_api_error(exc: BaseException, action: str) -> OperationServiceError:
    """把公共库 ``RuntimeError`` 包成 ``OperationServiceError``。

    统一「交用户决策，勿自动重试」语义：调用方仍写
    ``raise wrap_api_error(exc, '<动作>') from exc``，产出与原手写模板
    ``f'{action}失败：{exc}；请停止并交用户决策，勿自动重试'`` 完全一致的 message。
    ``action`` 即 message 中「失败」前的完整前缀（如「查询详情」「上传失败：申请上传地址」）。
    """
    return OperationServiceError(
        f'{action}失败：{exc}；请停止并交用户决策，勿自动重试'
    )


def ensure_full_search_results(search_path: str, *, dispatcher=None) -> dict:
    """全量保障：``isFull≠true`` 时续拉回写 search.jsonl，返回刷新后的 header。

    统一 organize plan 与 refine 共用的「全量保障 + 错误转译」块——本地
    ``services.search_fetch`` 的 ``FetchYield`` 原样上抛（让出 ≠ 失败，重跑即
    续拉），其余异常包成 ``OperationServiceError`` 交用户决策。

    Args:
        search_path: search.jsonl 的路径（``str(input_path)`` 或 ``str(session.search_path)``）。
        dispatcher: 可选注入（测试用 fake）；缺省公共库 dispatcher。

    Returns:
        续拉后刷新的 header dict。调用方据此判定已全量（``isFull=true``）。
    """
    from services.search_fetch import FetchYield, ensure_full_results

    try:
        _files, header, _pulled = ensure_full_results(search_path, dispatcher=dispatcher)
    except FetchYield:
        raise
    except ValueError as exc:
        raise OperationServiceError(f'读取搜索结果失败：{exc}') from exc
    except RuntimeError as exc:
        raise OperationServiceError(
            f'全量保障拉取失败：{exc}；请停止并交用户决策，勿自动重试'
        ) from exc
    except Exception as exc:  # noqa: BLE001 兜底转译
        raise OperationServiceError(
            f'读取搜索结果失败：{exc}；请确认 --from 传的是 search 产的 handle'
        ) from exc
    return header


__all__ = ['CliValidationError', 'OperationServiceError', 'wrap_api_error', 'ensure_full_search_results']
