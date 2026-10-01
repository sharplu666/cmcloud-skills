'''
Descripttion: 
version: 
Author: lixuezhi
Date: 2026-07-02 09:55:34
LastEditors: lixuezhi
LastEditTime: 2026-07-02 14:18:55
'''
import os
import uuid
from pathlib import Path


PLAN_LOG_DIR_NAME: str = 'plan_log'
SEARCH_SOFT_TIME_BUDGET_SEC: int = 500
SEARCH_FETCH_CHECKPOINT_MIN: int = 2000
SEARCH_PROGRESS_EVERY: int = 2000
MAX_FETCH_FILES: int = 50000


class AllSetting:
    # 当前会话标识，由 ``MCLAW_CURRENT_SESSION`` 环境变量决定，未设置时为 None
    MCLAW_CURRENT_SESSION: str | None = os.getenv('MCLAW_CURRENT_SESSION')


class ProjectSettings(AllSetting):
    PROJECT_NAME = "openclaw"  # 项目标识，用于日志与部署命名
    LOG_ROOT_DIR = "tmp/logs"  # 相对日志根目录（非 AI 空间 dynamic_log）


class AuthEnvSettings(AllSetting):
    """鉴权 ``.env`` 路径配置。

    所有路径基于 ``common`` 包根（``dev/skills/common/``）解析，与
    ``mclaw.api.auth`` 解耦，便于统一调整部署布局。

    ``.env`` 查找顺序（后者覆盖前者，运行时由 ``auth._read_env_values`` 应用）：
      1. ``COMMON_API_ENV_FILE`` —— ``mclaw/api/.env``（同目录兜底）
      2. ``CM_CLOUD_ENV_FILE`` 环境变量指向的文件（最高优先级）
    """

    _COMMON_ROOT = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    )  # ``dev/skills/common/`` 包根，用于解析下方 .env 路径
    COMMON_API_ENV_FILE = os.path.join(_COMMON_ROOT, 'api', '.env')  # 鉴权 .env 兜底路径（优先级低于 CM_CLOUD_ENV_FILE）


class AiSpaceLogSettings(AllSetting):
    """AI 空间动态日志配置。

    统一管理 AI 空间日志的 workspace 根目录、子目录名与日志文件名。业务代码
    统一 ``from mclaw.utils.settings import AiSpaceLogSettings`` 后用
    ``AiSpaceLogSettings.FIELD`` 引用。

    实际落盘路径 = ``<WORKSPACE_DIR>/<LOG_DIR_NAME>/<YYYY-MM-DD>/<LOG_FILE>``，
    由 ``mclaw.api.base._ai_space_log.append_ai_space_log`` 首次写入时拼接
    并创建父目录。

    ``LOG_FILE`` 在模块加载时生成一次（``{sessionId}_{uuid_hex}.jsonl``），
    整个进程生命周期共用；sessionId 取自环境变量，未设置时为空串。
    """

    # workspace 根目录；由 ``OPENCLAW_WORKSPACE`` 环境变量决定，默认 ``/home/node/.openclaw/workspace``
    WORKSPACE_DIR: str = os.getenv('OPENCLAW_WORKSPACE', '/home/node/.openclaw/workspace')
    # 日志子目录名（位于 workspace 根下）
    LOG_DIR_NAME: str = 'dynamic_log'
    # 日志文件名：模块加载时生成一次，整个进程生命周期共用
    LOG_FILE: str = f"{os.getenv('sessionId', '')}_{uuid.uuid4().hex}.jsonl"


class GlobalLogInfoSettings(AllSetting):
    """全局日志 info_dict 字段（status_log 自动注入）。

    所有字段在模块加载时确定，整个进程生命周期共用。``status_log`` 调用前
    会把这些字段合并到 ``info_dict``；调用方显式传入的同名 key 优先（覆盖
    全局值）。后续需要新增全局日志字段（如 service/env）直接在此扩展。

    业务代码统一 ``from mclaw.utils.settings import GlobalLogInfoSettings``
    后只读引用 ``GlobalLogInfoSettings.REQUEST_ID``，禁止运行时改值
    （类属性改写会影响整个进程，需谨慎，必要时新增字段而非改值）。

    会话 / 工具调用 / 实例标识（currentSession / toolCallId / sessionId /
    openclawId）不在此随每条日志注入——它们在进程内恒定，重复打印是噪声；
    改由 ``import mclaw`` 时打印一次启动行（见 ``logger.log_runtime_env``），
    全局只用 ``requestId`` 做跨条目追踪。
    """

    # 进程级 requestId，模块加载时生成一次；16 位 uuid
    REQUEST_ID: str = uuid.uuid4().hex[:16]


class ApiTimeoutSettings(AllSetting):
    """Open API 单次 POST 超时（秒），按接口路径命名。

    mclaw ``*Api.TIMEOUT`` 应引用本类对应字段；直连 HTTP（如 ``cm_cloud_http``）
    用 ``api_timeout_for_path(path)`` 按 ``PATH`` 查表。未收录路径用 ``DEFAULT_SEC``。
    """

    DEFAULT_SEC: int = 60

    # search_fusion
    SEARCH_MERGE_IMAGE_SEC: int = 120
    SEARCH_MERGE_FILE_SEC: int = 120
    SEARCH_BY_FILE_ID_SEC: int = 120

    # personal_saas — 异步批量提交
    FILE_BATCH_COPY_SEC: int = 120
    FILE_BATCH_MOVE_ASYNC_SEC: int = 120
    TASK_GET_SEC: int = 30

    # operation
    PHOTO_ORGANIZE_SUBMIT_SEC: int = 60
    PHOTO_ORGANIZE_QUERY_SEC: int = 30
    PHOTO_ORGANIZE_RETRY_SEC: int = 30

    # aiService
    IMAGE_DEDUPLICATE_SEC: int = 60

    # album — openclaw 批量图片去重（异步任务）
    IMAGE_BATCH_DEDUP_SUBMIT_SEC: int = 60
    IMAGE_BATCH_DEDUP_RESULT_SEC: int = 30

    # album — AI 选图（异步任务）
    SELECT_PHOTO_SUBMIT_SEC: int = 60
    SELECT_PHOTO_RESULT_SEC: int = 30
    # resultUrl 结果文件下载 (connect, read) 拆对：connect 短判死不可达，
    # read 容忍弱网传输间隔（KB 级结果文件；2026-09-11 单值 60 拆对）
    SELECT_PHOTO_DOWNLOAD_CONNECT_SEC: int = 5
    SELECT_PHOTO_DOWNLOAD_SEC: int = 30

    # videosec — AI 视频创作
    VIDEO_CREATION_ESTIMATE_SEC: int = 60
    VIDEO_CREATION_CREATE_SEC: int = 60
    VIDEO_CREATION_QUERY_SEC: int = 30


_API_PATH_TIMEOUT_SEC: dict[str, int] = {
    '/richlifeApp/aiService/api/text/intelligent/search/merge/image': (
        ApiTimeoutSettings.SEARCH_MERGE_IMAGE_SEC
    ),
    '/richlifeApp/aiService/api/text/intelligent/search/merge/file': (
        ApiTimeoutSettings.SEARCH_MERGE_FILE_SEC
    ),
    '/richlifeApp/aiService/api/text/intelligent/search/merge/image/aiAnalysisInfo': (
        ApiTimeoutSettings.SEARCH_BY_FILE_ID_SEC
    ),
    '/richlifeApp/personalSaas/file/batchCopy': ApiTimeoutSettings.FILE_BATCH_COPY_SEC,
    '/richlifeApp/personalSaas/file/batchMoveAsync': (
        ApiTimeoutSettings.FILE_BATCH_MOVE_ASYNC_SEC
    ),
    '/richlifeApp/personalSaas/task/get': ApiTimeoutSettings.TASK_GET_SEC,
    '/richlifeApp/api/openclaw/photoOrganize/task': ApiTimeoutSettings.PHOTO_ORGANIZE_SUBMIT_SEC,
    '/richlifeApp/api/openclaw/photoOrganize/task/query': ApiTimeoutSettings.PHOTO_ORGANIZE_QUERY_SEC,
    '/richlifeApp/api/openclaw/photoOrganize/task/retry': ApiTimeoutSettings.PHOTO_ORGANIZE_RETRY_SEC,
    '/richlifeApp/aiService/api/image/deduplicate': ApiTimeoutSettings.IMAGE_DEDUPLICATE_SEC,
    '/richlifeApp/api/openclaw/deduplicate/submit': (
        ApiTimeoutSettings.IMAGE_BATCH_DEDUP_SUBMIT_SEC
    ),
    '/richlifeApp/api/openclaw/deduplicate/result': (
        ApiTimeoutSettings.IMAGE_BATCH_DEDUP_RESULT_SEC
    ),
    '/richlifeApp/api/image/asyncSelectPhoto': (
        ApiTimeoutSettings.SELECT_PHOTO_SUBMIT_SEC
    ),
    '/richlifeApp/api/image/selectPhotoResult': (
        ApiTimeoutSettings.SELECT_PHOTO_RESULT_SEC
    ),
    '/richlifeApp/api/videosec/videocreation/task/estimate': (
        ApiTimeoutSettings.VIDEO_CREATION_ESTIMATE_SEC
    ),
    '/richlifeApp/api/videosec/videocreation/task/create': (
        ApiTimeoutSettings.VIDEO_CREATION_CREATE_SEC
    ),
    '/richlifeApp/api/videosec/videocreation/task/query': (
        ApiTimeoutSettings.VIDEO_CREATION_QUERY_SEC
    ),
}


def api_timeout_for_path(path: str) -> int:
    """按 Open API 路径返回单次 POST 超时（秒）。"""
    key = '/' + str(path or '').strip().lstrip('/')
    return _API_PATH_TIMEOUT_SEC.get(key, ApiTimeoutSettings.DEFAULT_SEC)


class AsyncTaskWaitSettings(AllSetting):
    """异步 task/get 轮询：按提交接口区分等待策略（非单次 HTTP 超时）。"""

    FILE_BATCH_COPY_POLL_INTERVAL_SEC: float = 5.0
    FILE_BATCH_COPY_WAIT_SEC: float = 3600.0

    FILE_BATCH_MOVE_POLL_INTERVAL_SEC: float = 5.0
    FILE_BATCH_MOVE_WAIT_SEC: float = 3600.0

    PHOTO_ORGANIZE_POLL_INTERVAL_SEC: float = 5.0
    PHOTO_ORGANIZE_POLL_WAIT_SEC: float = 3600.0


def plan_log_dir() -> Path:
    """当前 ``OPENCLAW_WORKSPACE/plan_log``（每次调用读取环境变量）。"""
    workspace = Path(os.getenv('OPENCLAW_WORKSPACE', '/home/node/.openclaw/workspace'))
    return workspace / PLAN_LOG_DIR_NAME


def photo_organize_poll_wait() -> tuple[float, float]:
    """图片整理任务 query 轮询间隔与总等待时长（秒）。"""
    return (
        AsyncTaskWaitSettings.PHOTO_ORGANIZE_POLL_INTERVAL_SEC,
        AsyncTaskWaitSettings.PHOTO_ORGANIZE_POLL_WAIT_SEC,
    )


def async_task_wait_for_action(action: str) -> tuple[float, float]:
    """按任务动作名返回 ``(poll_interval_sec, wait_timeout_sec)``。

    ``action`` 为 ``batch_move`` 时用移动配置，其余（含 ``batch_copy``）用复制配置。
    """
    if str(action or '').strip() == 'batch_move':
        return (
            AsyncTaskWaitSettings.FILE_BATCH_MOVE_POLL_INTERVAL_SEC,
            AsyncTaskWaitSettings.FILE_BATCH_MOVE_WAIT_SEC,
        )
    return (
        AsyncTaskWaitSettings.FILE_BATCH_COPY_POLL_INTERVAL_SEC,
        AsyncTaskWaitSettings.FILE_BATCH_COPY_WAIT_SEC,
    )


class HttpSettings(AllSetting):
    """Open API HTTP 重试等全局调参。

    单次 POST 超时见 ``ApiTimeoutSettings`` / ``api_timeout_for_path``；
    异步任务轮询见 ``AsyncTaskWaitSettings``。
    """

    DEFAULT_MAX_RETRIES: int = 3
    DEFAULT_RETRY_DELAY_SEC: float = 2.0


class CardSetting(AllSetting):
    """卡片防复述：每张卡 stdout 用 frontend_card 标签包裹，输出末尾追加 agent_note 说明。

    由 ``mclaw.shared.cm_cloud.card_meta`` 的 ``frontend_card_tags`` / ``card_end_note`` 消费。
    """

    FRONTEND_CARD_OPEN_TMPL: str = '<frontend_card name="{card}">'
    FRONTEND_CARD_CLOSE: str = '</frontend_card>'
    CARD_END_NOTE_LINES: tuple[str, ...] = (
        '<agent_note source="mclaw">',
        '本次输出中 <frontend_card> 包裹的卡片（{names}）已由前端插件渲染给用户，复述该卡片无法调用前端插件。',
        '你的回复严禁出现 ":::"、<frontend_card> 标签、卡片名或块内JSON；本提示本身也不得复述。',
        '请用纯文本向用户说明上述卡片的结果。',
        '</agent_note>',
    )
