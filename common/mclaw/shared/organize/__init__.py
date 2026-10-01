#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mclaw.shared.organize —— 个人云整理（organize）共享业务编排层。

本子包承载从 ``cm_cloud_organize`` 提取的、可跨 skill 复用的整理逻辑。
当前提供：

  - ``bucket``：桶（Bucketer）注册中心 + 聚类画像
    （从 ``cm_cloud_organize/scripts/bucket/`` 迁移，``File`` 改用
    ``mclaw.api.search_fusion._models`` 的 Pydantic v2 ``File``）
  - ``selector``：桶 × N / 全集 top-N 图片质量挑选 + 聚类产物 top 裁剪
    （``apply_select_to_flat`` / ``apply_select_to_tree``）
  - ``cluster_ops`` / ``preview_cards``：聚类分桶与预览卡片（manage / organize 共用；搜索卡 ``meta.summary`` 与 ``--top`` 分桶标题同一套文案）
  - ``presearch_paging``：预搜索拉全量 API 分页常量（与 organize Step 2 对齐）
  - ``tools``：搜索结果 ``List[File]`` 的 JSONL 落盘与读回
    （从 ``cm_cloud_organize/scripts/search_results_io.py`` 迁移；落盘位置由
    调用方显式传入，不读任何配置 / 环境变量）
  - ``organize_session``：整理会话（handle）管理——一个整理任务一个短 id，
    对应 ``<plan_log>/<handle>/`` 目录（search.jsonl / plan.jsonl / meta.json），
    各阶段用 handle 接续，模型只记短 id 不背长路径
  - ``photo_organize_task``：photoOrganize 任务生命周期（submit / query / retry）+
    plan rows → 服务端行转换 ``to_server_rows``；经 ``dispatcher.operation.*`` 调封装好的 API
  - ``dedup``：``collapse_exact_duplicates`` 为 contentHash 精确去重
    （本地零网络，与相似图 API 去重互补）
  - ``transforms``：组内去重 + 精选变换（``transform_leaf_files``），organize plan 内嵌，
    不落 subset jsonl；drive/album 逐桶去重/精选共用
  - ``organize_cards``：organize 任务卡片决策与发射（submit/status/retry 共用），
    按 task_type 路由卡名（drive→filePathList / album→albumList / memory→memoryAlbum）

与 ``cm_cloud_organize/scripts/bucket`` 的差异：
  - ``File`` 来源：本模块用 ``mclaw.api.search_fusion._models.File``
    （Pydantic v2，snake_case 字段 + camelCase alias），原模块用本地
    ``file_model.File``（dataclass，camelCase 字段）。
  - 阈值：原模块从 ``manage_bootstrap.load_organize_settings()`` 读
    ``CLUSTER_SET_THRESHOLD``；本模块固化 ``DEFAULT_SET_THRESHOLD = 30``，
    调用方需要时显式传 ``threshold``。
  - 包内 import 全部走绝对路径 ``mclaw.shared.organize.bucket.<mod>``，
    不再依赖 ``sys.path`` 注入 ``scripts/``。

设计原则（与 ``mclaw.shared`` 一致）：
  - 本包默认**不发 HTTP、不持鉴权/host**。``File`` 仅作为桶提取的输入数据结构，
    由调用方自行通过 ``mclaw.api.search_fusion`` 检索得到。
  - 唯一例外是 ``photo_organize_task.OrganizeTaskClient``：它经
    ``mclaw.shared.cm_cloud.cloud_dispatcher.get_cloud_dispatcher()`` 调封装好的 API
    （``dispatcher.operation.*``，含鉴权/重试/trace），与 ``shared.cm_cloud.folder_ops``
    调 ``dispatcher.personal_saas.create_folder`` 同性质——不是在 shared 里拿
    ``requests`` 直接拼 URL 发请求。``organize_session`` 仍纯文件编排、不发 HTTP。
"""

from mclaw.shared.organize import bucket  # noqa: F401
from mclaw.shared.organize import dedup  # noqa: F401
from mclaw.shared.organize import organize_cards  # noqa: F401
from mclaw.shared.organize import organize_session  # noqa: F401
from mclaw.shared.organize import photo_organize_task  # noqa: F401
from mclaw.shared.organize import search_fetch_store  # noqa: F401
from mclaw.shared.organize import selector  # noqa: F401
from mclaw.shared.organize import tools  # noqa: F401
from mclaw.shared.organize import transforms  # noqa: F401

__all__ = [
    'bucket',
    'dedup',
    'organize_cards',
    'organize_session',
    'photo_organize_task',
    'search_fetch_store',
    'selector',
    'tools',
    'transforms',
]
