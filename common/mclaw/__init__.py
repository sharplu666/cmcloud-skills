"""mclaw 包入口。

注册 ``atexit`` 钩子：进程退出时向 stdout 输出辅助标记，供 CLI 上层感知
本次运行的状态信息。具体钩子实现集中在 ``mclaw.utils.exit_hooks``，本模块
只调用 ``register_exit_hooks()`` 一次。

当前注册的退出标记：

1. ``<log_path>...</log_path>`` —— AI 空间日志文件路径（仅当已写入记录）。
2. ``<debug>requestId=...</debug>`` —— 本次进程的全局 requestId。

启动时打印一次运行时环境变量（会话 / 工具调用 / 实例标识）：见
``mclaw.utils.logger.log_runtime_env``。这些值进程内恒定，无需随每条
``status_log`` 重复——全局只用 ``requestId`` 做跨条目追踪。

注意：本导入会触发 ``mclaw.api`` 子包加载，进而可能加载鉴权与 pycryptodome
等依赖。caller 仅需 ``mclaw.utils.settings`` 等独立模块时，应直接导入该子模块
而非 ``import mclaw``。
"""

from mclaw.utils.exit_hooks import register_exit_hooks
from mclaw.utils.logger import log_runtime_env


register_exit_hooks()
log_runtime_env()
