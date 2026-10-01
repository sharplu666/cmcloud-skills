#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.shared —— 业务编排层。

存放跨 skill 复用的业务流程编排代码（如结果文件归档、轮询结果输出处理）。
与 ``mclaw/api/`` 的区别：
  - ``api/`` 是 HTTP 原子能力（每个文件对应一个后端接口），由 ``ApiDispatcher`` 调度
  - ``shared/`` 是业务编排，**不发 HTTP、不持鉴权**，所有 HTTP 调用通过调用方注入的
    ``dispatcher: ApiDispatcher`` 完成（属性链 ``d.<namespace>.<leaf>(req)``）
"""
