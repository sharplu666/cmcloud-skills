#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cm_cloud_manage 全局配置：鉴权、路径、分页、退出码、输出与 API 调参。"""

from __future__ import annotations

import os
import sys

# --- 运行时引导：注入 common_auth / mclaw 到 sys.path（import utils.config 时执行）---
_SCRIPTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
_SKILL_ROOT = os.path.abspath(os.path.join(_SCRIPTS_ROOT, '..'))
_COMMON_AUTH = os.path.join(_SKILL_ROOT, '..', 'common_auth')
_MCLAW_ROOT = os.path.join(_SKILL_ROOT, '..', 'common')
for _p in (_COMMON_AUTH, _MCLAW_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mclaw.api.auth import get_skill_auth

# =============================================================================
# 鉴权与部署
# =============================================================================

# 仅取 host / app_name（.env）；API 请求头走 get_auth_header()，勿复用本对象缓存 token
auth_config = get_skill_auth()
HOST = auth_config.host  # 个人云 Open API 根地址
APP_NAME = str(auth_config.app_name or '').strip()  # 应用名，参与拼 MClaw 空间路径

# =============================================================================
# 目录与空间路径
# =============================================================================

AI_SPACE_DIR_NAME = 'AI空间'  # 云盘 AI 空间顶层目录名
CHAT_FILE_DIR_NAME = '对话文件'  # 会话默认上传目录在 MClaw 下的子目录名
MCLAW_ALLOWED_DIR = f'/{AI_SPACE_DIR_NAME}/{APP_NAME}'  # 本技能可写根路径，如 /AI空间/MClaw空间
WORKSPACE_DIR = '/home/node/.openclaw/workspace'  # OpenClaw 工作区路径（日志等落盘参考）

# =============================================================================
# 进程退出码
# =============================================================================

EXIT_OK = 0  # 成功
EXIT_INPUT_ERROR = 1  # 入参不合法
EXIT_BUSINESS_ERROR = 2  # 业务/API 失败或部分失败
EXIT_INTERNAL_ERROR = 3  # 未预期内部错误

# =============================================================================
# CLI 子命令分类
# =============================================================================

WRITE_COMMANDS = frozenset({
    'upload', 'batch_copy', 'batch_move', 'batch_rename', 'mkdir',
})  # 写操作：需初始化 operation_log

SEARCH_LIST_COMMANDS = frozenset({
    'search',
})  # 走 merge/file 的搜文件/列举：API 分页默认 MERGE_SEARCH_PAGE_SIZE；纯搜索卡片展示受 SEARCH_CARD_DISPLAY_LIMIT 约束。
# 检索命令（search/dynamic 现行实现）不走出卡链 emit_meta_and_files——
# 卡片由 services/search/stdout_receipt.emit_card 直发，本集合对它们不生效。

FILE_PATH_AGGREGATE_COMMANDS = frozenset({
    'upload', 'batch_copy', 'batch_move', 'batch_rename', 'batch_get', 'batch_check_exists',
})  # 成功时在 meta 中附带 filePathList 的子命令

# =============================================================================
# search-by-ids：按 fileId 精确取文件详情（仅文件 id，folder 拒绝并指路 search）
# =============================================================================

SEARCH_BY_IDS_MAX_IDS = 500  # 接口层：by-fileId fileList 单次上限（对齐 merge/image/aiAnalysisInfo）
SEARCH_BY_IDS_CLI_MAX_IDS = 20  # CLI 层：--file-ids 输入上限（防参数幻觉）

BATCH_RENAME_MAX = 100  # batch_rename 单次最多重命名条数
BATCH_COPY_MOVE_MAX = 30  # batch_copy / batch_move 单次最多文件数；超出需改用「云盘文件管理」整理流程

MOVE_SKIP_OUTSIDE_MCLAW_PREFIX = (
    f'文件不在「{MCLAW_ALLOWED_DIR}」内，无移动权限，已跳过'
)  # batch_move 跳过非 MClaw 空间文件时的提示前缀

# =============================================================================
# 搜文件 / 搜图：分页与列表展示
# =============================================================================

MERGE_SEARCH_PAGE_SIZE = 10  # merge/file 搜文件与 list：--page-size 默认值（API 每页条数）
SEARCH_IMAGE_PAGE_SIZE = 10  # 语义搜图（semantic-search）API 每页条数
SEARCH_CARD_DISPLAY_LIMIT = 10  # 纯搜索（无 --top/--bucket）时 fileList/imageList 卡片最多展示条数
LIST_DISPLAY_LIMIT = 50  # 非搜文件类命令（如 batch_get）fileList 卡片默认展示条数上限

# =============================================================================
# 全量拉取 OOM 上限
# =============================================================================

MAX_FETCH_FILES = 50000  # 全量拉取累计去重行数硬上限（≈252MB）：search_fetch 续拉 / person full / search full 共用

# =============================================================================
# 检索回执指引（searchResults 交接行按命中数附带的非阻断提示）
# =============================================================================

SEARCH_LOW_RESULTS_TIPS_THRESHOLD = 50  # 命中数 ≤ 该值 → 附 tips（如实汇报约束）
# 命中较少（模型向）：约束「如实汇报 + 勿自动改条件重搜」，防结果过少时反复搜索
SEARCH_LOW_RESULTS_TIPS_MESSAGE = (
    '搜索已完成：请将本次搜索条件与实际命中数如实告知用户，'
    '勿自行调整条件重复搜索，是否重搜由用户决定。'
)
# 命中为空（用户向，模型原样转述）：在 tips 之上按 searchKind 给可操作的无结果建议
SEARCH_ZERO_RESULTS_SAY_TO_USER = {
    'semantic-person': '没有找到对应的照片，可以换一张人脸清晰的参考图，或者放宽查找条件再试试。',
    'semantic-image': '没有找到符合条件的照片，可以换个描述再试试等筛选条件。',
    'image-file': '没有找到符合条件的照片，可以换个关键词再试试，或放宽时间、类型等筛选条件。',
    'file-search': '没有找到符合条件的文件，可以换个关键词再试试，或放宽时间、类型等筛选条件。',
    'image-dynamic': '该时间段没有找到图片动态，可以调整时间范围或关键词再试试。',
    'file-dynamic': '该时间段没有找到动态，可以调整时间范围或类型再试试。',
    'audio-dynamic': '该时间段没有找到音频动态，可以调整时间范围再试试。',
    'video-dynamic': '该时间段没有找到视频动态，可以调整时间范围再试试。',
}
# person-search 未检出目标人脸（业务码 10000041 / 空壳）零命中时 tips 前置的
# 友好提示（模型向；尾带「；」与 SEARCH_LOW_RESULTS_TIPS_MESSAGE 拼接）
PERSON_NO_TARGET_TIPS_PREFIX = '抱歉，暂时没能在图片里找到对应的目标内容哦；'
# search-transfer 命中 0（用户向，模型原样转述）
SEARCH_TRANSFER_ZERO_RESULTS = '该时间段没有找到转存记录，可以调整时间范围再试试。'

# =============================================================================
# 精选/回忆故事回执文案（refine select 与 organize image plan 共用，用户向）；
# 占位符 <name> 由调用方 str.replace 渲染，完整句模板集中于此统一管理
# =============================================================================

# refine select 未选满（保留数 < --pick）：整集（不用「素材不足」缺口腔，2026-09-03 定案）
REFINE_SELECT_UNDER_PICK_WHOLE = '（可精选的照片只有 <kept> 张，已全部为你选出）'
# refine select 未选满：分桶点名未选满桶——未选满桶数 ≤ REFINE_SAY_BUCKET_DETAIL_MAX
# 时用此模板，<buckets> 填「、」连接的「桶名」列表
REFINE_SELECT_UNDER_PICK_BUCKETS = '（<buckets>可精选的照片不足 <pick> 张，已全部为你选出）'
# refine select 未选满：未选满桶数 > REFINE_SAY_BUCKET_DETAIL_MAX 时点名无信息量，
# 降级为不点名（明细仍在回执 data.buckets 供追问）
REFINE_SELECT_UNDER_PICK_BUCKETS_MANY = '（部分分类可精选的照片不足 <pick> 张，已全部为你选出）'
# refine select 分桶时整桶精选后保留 0（AI 选图空 / 质量门剔空）的桶级提示：
# 桶级可观测（否则桶静默消失、总数变少无从解释）；点名上限同 REFINE_SAY_BUCKET_DETAIL_MAX
REFINE_SELECT_EMPTY_BUCKETS = '（<count> 个分类精选后无保留照片，已跳过：<buckets>）'
REFINE_SELECT_EMPTY_BUCKETS_MANY = '（<count> 个分类精选后无保留照片，已跳过）'
# refine 去重/精选后零保留：正常 ok 回执（非 error），对齐 search 零命中收束口径
REFINE_NO_SURVIVORS_SAY = '去重/精选后无保留文件；请调整 --pick 或换搜索条件'
# 精选质量门的规则说明（零存活回执追加；规则说明式不断言死因——AI 选图路径同样
# 先过此门，此句在两条路径下均真实）。refine select 与 organize memory 零存活共用；
# dedup 不加门，勿附加（误导死因）
MEMORY_PHOTO_GATE_HINT = '（精选会先剔除无拍摄时间与证件/截图类图片）'
# 分桶 say 点名阈值（「详情：」行与未选满点名共用；超过则均不点名）
REFINE_SAY_BUCKET_DETAIL_MAX = 5
# refine per-bucket 逐桶并行上限（与公共库 REFINE_MEMORY_MAX_WORKERS 同值、各自独立）。
# 外层桶并行时桶内相似图去重降 max_workers=1 收敛嵌套；单桶/本值≤1 退化为串行。
REFINE_TRANSFORM_MAX_WORKERS = 4
# refine select / organize memory 的选图引擎开关：True=AI 选图异步接口
# （album.select_photo_submit/result，替换「相似图 API 去重 + imgQuality top-N」两步，
# 其余步骤不变；提交/轮询异常自动打日志并回退旧两步）；False=保持原链路。
USE_SELECT_PHOTO = True
# organize image plan 精选括号（总数由回执开头「共 N 张」承载，不重复报保留数）
MEMORY_REFINE_NOTE = (
    '（已过滤 <filtered> 张、去重 <deduped> 张，'
    '每个<label>最多存入 <top> 张图片，按质量评分精选）'
)
# organize image plan 非图片过滤说明（album|memory 仅收图片；实际剔除 >0 时
# 追加进 sayToUser，image_plan 渲染 <label>/<kept>/<removed>）
IMAGE_NON_IMAGE_FILTER_NOTE = (
    '；<label>生成仅支持图片，目前图片 <kept> 张，'
    '过滤非图片格式的文件 <removed> 个'
)
# organize plan 多标签分桶计数提示（多值维度分桶且各桶计数相加 > 去重文件总数时
# 追加进 sayToUser；图片/文件两版措辞，plan_common.multi_label_overlap_note 渲染
# <total>/<distinct>）
MULTI_LABEL_OVERLAP_NOTE_IMAGE = (
    '；提示：多标签分类下一张图片会同时进多个类别，'
    '根据类别计算图片总数 <total> 会大于图片总数 <distinct> 张'
)
MULTI_LABEL_OVERLAP_NOTE_FILE = (
    '；提示：多标签分类比下一个文件会同时进多个类别，'
    '根据类别计算文件总数相加 <total> 会大于文件总数 <distinct> 个'
)

# =============================================================================
# API 批量与搜索调参
# =============================================================================

BATCH_SUBREQUEST_MAX = 100  # batchGet / batchGetPath 等单次请求 fileId 上限
# sizeRange 默认上下限与可筛选类型权威定义见
# ``mclaw.shared.postprocess.search_param``（DEFAULT_SEARCH_SIZE_* / SIZE_FILTER_FILE_TYPES）

# merge/file 请求 typeList 常用取值（与产品资产类型编码一致）

# merge/search 请求 searchType 字面量（非 HTTP path）
SEARCH_TYPE_FILE = 'File'  # 搜文件（关键词/筛选/备份/list）
SEARCH_TYPE_SEMANTIC_IMAGE = 'SemanticImage'  # 语义搜图
SEARCH_TYPE_IMAGE_FILE = 'ImageFile'  # 按图搜文件

SEARCH_TYPES_FILE_LIST_CONTROL = frozenset({SEARCH_TYPE_FILE, SEARCH_TYPE_IMAGE_FILE})
# 使用 :::fileList 卡片控制行的搜索类型（不含纯语义搜图）

# =============================================================================
# 输出卡片与渲染
# =============================================================================

CARD_FILE_LIST = 'fileList'  # 文件列表卡片块名
CARD_IMAGE_LIST = 'imageList'  # 图片/相册列表卡片块名

LOAD_MORE_TOTAL_THRESHOLD = 10  # 总命中数超过该值时在卡片头展示「加载更多」提示

# =============================================================================
# 异步批量任务（复制 / 移动 / 整理）
# =============================================================================

BATCH_FOLDER_CHILDREN_PAGE_SIZE = 500  # batch_rename 完成后列举目标文件夹子项时的 pageSize
