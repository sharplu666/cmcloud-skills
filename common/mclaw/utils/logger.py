import os
import re
import sys
import time
import logging
import socket
from stat import ST_MTIME
from typing import Optional
from logging import handlers
from logging.handlers import BaseRotatingHandler, RotatingFileHandler, TimedRotatingFileHandler
from .settings import ProjectSettings


# 与标准库 logging.handlers 一致的一天秒数，用于按时间滚动计算
_MIDNIGHT = 24 * 60 * 60  # number of seconds in a day


class SizeTimedRotatingFileHandler(BaseRotatingHandler):
    """按「总大小 + 年龄 + 时间」管理日志的文件 handler。

    触发与删除规则（满足实际运维诉求，而非标准库的「保留 N 个」语义）：

      - **按时间触发滚动**：到达指定时刻（默认每天午夜）把当前 ``xxx.log`` 归档为
        ``xxx.log.<日期>``（如 ``xxx.log.2026-07-05``），便于按天排查；
      - **按总大小触发滚动**：当前活跃文件 ``xxx.log`` 大小达到 ``maxBytes``
        （即整个日志族上限的「单文件预算」）时立即归档为 ``xxx.log.1`` /
        ``xxx.log.2`` / ...，避免单文件无限增长。
      - **年龄删除**：归档文件 mtime 超过 ``maxAgeDays`` 天的，无条件删除。
      - **总大小裁剪**：归档族总大小（不含活跃文件）超过 ``totalSizeBytes`` 时，
        按 mtime 从旧到新删归档，直到回落到上限内。

    与标准库 ``RotatingFileHandler`` 的 ``backupCount`` 不同：这里上限不是「文件个数」
    而是「总字节数」+「最大年龄」，二者独立作用、先删过期的、再删超量的。

    实现说明：以 ``BaseRotatingHandler`` 为基类，``doRollover`` 的数字后缀链式重命名
    借鉴 ``RotatingFileHandler``；时间触发逻辑（``rolloverAt`` / ``computeRollover``）
    与标准库 ``TimedRotatingFileHandler`` 一致，仅支持 ``MIDNIGHT``。

    测试：见 ``common/tests/logger/``：
      - ``test_logger_rotation.py`` —— pytest 单测，断言驱动覆盖三种滚动；
      - ``test_openclaw_logger_demo.py`` —— 演示脚本，真实 import ``openclaw_logger``
        观察滚动效果（验证前临时调小 ``maxBytes``/``totalSizeBytes``，验证完改回）。
    """

    def __init__(self, filename, mode='a', maxBytes=0, totalSizeBytes=0,
                 maxAgeDays=0, encoding=None, delay=False, utc=False,
                 atTime=None, errors=None):
        BaseRotatingHandler.__init__(self, filename, mode, encoding=encoding,
                                     delay=delay, errors=errors)
        self.maxBytes = maxBytes            # 单文件大小上限：达到即滚动（数字后缀）
        self.totalSizeBytes = totalSizeBytes  # 归档族总大小上限：超出删最旧归档
        self.maxAgeDays = maxAgeDays        # 归档最大保留天数：超期无条件删
        self.utc = utc
        self.atTime = atTime
        # 仅支持按天滚动（MIDNIGHT），与 openclaw_logger 用途一致；如需更细粒度
        # 时间触发，直接用标准库 TimedRotatingFileHandler。
        self.when = 'MIDNIGHT'
        self.interval = _MIDNIGHT
        # 时间归档后缀：xxx.log.2026-07-05
        self.suffix = "%Y-%m-%d"
        self.extMatch = r"^\d{4}-\d{2}-\d{2}(\.\w+)?$"
        self.extMatch = re.compile(self.extMatch, re.ASCII)

        filename = self.baseFilename
        if os.path.exists(filename):
            t = os.stat(filename)[ST_MTIME]
        else:
            t = int(time.time())
        self.rolloverAt = self.computeRollover(t)

    def computeRollover(self, currentTime):
        """计算下一次按时间滚动的时刻（逻辑与 TimedRotatingFileHandler 一致）。"""
        result = currentTime + self.interval
        if self.utc:
            t = time.gmtime(currentTime)
        else:
            t = time.localtime(currentTime)
        currentHour = t[3]
        currentMinute = t[4]
        currentSecond = t[5]
        if self.atTime is None:
            rotate_ts = _MIDNIGHT
        else:
            rotate_ts = ((self.atTime.hour * 60 + self.atTime.minute) * 60 +
                         self.atTime.second)
        r = rotate_ts - ((currentHour * 60 + currentMinute) * 60 + currentSecond)
        if r < 0:
            r += _MIDNIGHT
        result = currentTime + r
        return result

    def shouldRollover(self, record):
        """是否需要滚动：按时间到点 或 当前文件达 maxBytes 任一成立即滚动。"""
        # See #89564: 永远不对非普通文件滚动
        if os.path.exists(self.baseFilename) and not os.path.isfile(self.baseFilename):
            return False
        if self.stream is None:                 # delay was set...
            self.stream = self._open()
        # 按时间触发
        if int(time.time()) >= self.rolloverAt:
            return True
        # 按大小触发：当前活跃文件达到单文件预算
        if self.maxBytes > 0:
            msg = "%s\n" % self.format(record)
            self.stream.seek(0, 2)  # due to non-posix-compliant Windows feature
            if self.stream.tell() + len(msg) >= self.maxBytes:
                return True
        return False

    def doRollover(self):
        """执行滚动。按时间触发→日期后缀归档；按大小触发→数字后缀归档。"""
        if self.stream:
            self.stream.close()
            self.stream = None

        if int(time.time()) >= self.rolloverAt:
            # 按时间触发：归档为 xxx.log.<日期>
            currentTime = int(time.time())
            t = self.rolloverAt - self.interval
            if self.utc:
                timeTuple = time.gmtime(t)
            else:
                timeTuple = time.localtime(t)
            dfn = self.rotation_filename(self.baseFilename + "." +
                                        time.strftime(self.suffix, timeTuple))
            if os.path.exists(dfn):
                os.remove(dfn)
            self.rotate(self.baseFilename, dfn)
            self.rolloverAt = self.computeRollover(currentTime)
        else:
            # 按大小触发：数字后缀链式滚动 xxx.log.1/.2/...（与 RotatingFileHandler 一致）
            self._rolloverBySize()

        # 滚动后清理：先删过期归档，再按总大小裁剪
        self._cleanup()
        if not self.delay:
            self.stream = self._open()

    def _rolloverBySize(self):
        """按大小滚动：xxx.log → xxx.log.1，旧 .1 → .2，依此类推。

        与 ``RotatingFileHandler.doRollover`` 一致，但不在此处删归档——删除统一
        交给 ``_cleanup``（按年龄 + 总大小）。
        """
        # 找到当前最大编号，把整条链后移一位，再把活跃文件重命名为 .1
        next_index = self._maxBackupIndex() + 1
        dfn = self.rotation_filename("%s.%d" % (self.baseFilename, next_index))
        if os.path.exists(dfn):
            os.remove(dfn)
        self.rotate(self.baseFilename, dfn)

    def _maxBackupIndex(self):
        """返回当前数字后缀归档中的最大编号（无则 0）。"""
        dirName, baseName = os.path.split(self.baseFilename)
        if not os.path.exists(dirName):
            return 0
        max_idx = 0
        for fileName in os.listdir(dirName):
            m = re.match(r'^%s\.(\d+)$' % re.escape(baseName), fileName)
            if m:
                max_idx = max(max_idx, int(m.group(1)))
        return max_idx

    def _cleanup(self):
        """滚动后清理归档：先删过期（超 maxAgeDays），再按总大小裁剪（超 totalSizeBytes）。"""
        archives = self._listArchives()  # [(path, mtime, size), ...]
        if not archives:
            return

        # 1. 年龄删除：mtime 早于「now - maxAgeDays」的归档无条件删除
        if self.maxAgeDays > 0:
            cutoff = time.time() - self.maxAgeDays * _MIDNIGHT
            expired = [a for a in archives if a[1] < cutoff]
            for path, _, _ in expired:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if expired:
                archives = [a for a in archives if a not in expired]

        # 2. 总大小裁剪：归档族总大小超 totalSizeBytes 时，从最旧开始删
        if self.totalSizeBytes > 0:
            archives.sort(key=lambda a: a[1])  # mtime 升序：最旧在前
            total = sum(a[2] for a in archives)
            for path, _, size in archives:
                if total <= self.totalSizeBytes:
                    break
                try:
                    os.remove(path)
                    total -= size
                except OSError:
                    pass

    def _listArchives(self):
        """列出所有归档文件（不含活跃文件），返回 [(path, mtime, size), ...]。"""
        dirName, baseName = os.path.split(self.baseFilename)
        if not os.path.exists(dirName):
            return []
        result = []
        for fileName in os.listdir(dirName):
            if fileName == baseName:
                continue  # 跳过当前活跃文件
            # 数字后缀（按大小滚动）：xxx.log.1 / xxx.log.2 / ...
            is_numbered = re.match(r'^%s\.\d+$' % re.escape(baseName), fileName)
            # 日期后缀（按时间滚动）：xxx.log.2026-07-05
            is_dated = False
            if fileName.startswith(baseName):
                suffix = fileName[len(baseName):]
                if suffix and suffix[0] == '.' and self.extMatch.match(suffix[1:]):
                    is_dated = True
            if not (is_numbered or is_dated):
                continue
            path = os.path.join(dirName, fileName)
            try:
                st = os.stat(path)
                result.append((path, st.st_mtime, st.st_size))
            except OSError:
                continue
        return result

    def getFilesToDelete(self):
        """保留旧接口（外部可能的调用/兼容）：返回当前应删除的归档路径列表。"""
        # 该方法不再被 doRollover 内部使用（清理逻辑已拆到 _cleanup），保留为外部兼容入口
        return [a[0] for a in self._listArchives() if
                (self.maxAgeDays > 0 and a[1] < time.time() - self.maxAgeDays * _MIDNIGHT)]


def get_host_ip():
    ip = ''
    host_name = ''
    # noinspection PyBroadException
    try:
        sc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sc.connect(('8.8.8.8', 80))
        ip = sc.getsockname()[0]
        host_name = socket.gethostname()
        sc.close()
    except Exception:
        pass
    return ip, host_name


def set_uvicorn_logger(cfg):
    from uvicorn.config import LOGGING_CONFIG

    datefmt = "%Y-%m-%d %H:%M:%S"
    computer_ip, computer_name = get_host_ip()
    service_name = cfg.PROJECT_NAME
    fmt = (f'%(asctime)s.%(msecs)03d'
           f'|{computer_ip}|{computer_name}|{service_name}'
           f'|p%(process)d|t%(thread)d|%(levelname)s|API|||%(message)s')

    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = datefmt
    LOGGING_CONFIG["formatters"]["access"]["fmt"] = fmt

    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = datefmt
    LOGGING_CONFIG["formatters"]["default"]["fmt"] = fmt

    return LOGGING_CONFIG


def setup_logger(
        name: str,
        save: Optional[bool] = False,
        filename: Optional[str] = None,
        mode: str = 'a',
        distributed_rank: bool = False,
        stdout: bool = True,
        stderr: bool = False,
        socket: bool = False,
        rotating_size: bool = False,
        rotating_time: bool = False,
        rotating_size_time: bool = False,
        maxBytes: int = 500 * 1024 * 1024,
        totalSizeBytes: int = 500 * 1024 * 1024,
        maxAgeDays: int = 14,
        level: str = 'debug',
        backupCount: int = 10,
        extra_fmt: Optional[str] = "",

):
    """
    日志模块

    :param level: 日志级别
    :param name: 日志名称
    :param filename: 日志文件名
    :param mode: 写模式
    :param distributed_rank: 是否分布式
    :param stdout: 是否输出到 stdout
    :param stderr: 是否输出到 stderr（CLI 场景下 HTTP 排障日志应走 stderr，避免污染 JSONL）
    :param save: 是否保存日志文件
    :param socket: 是否输出到socket
    :param rotating_size: 是否按文件大小切割
    :param rotating_time: 是都按日期切割
    :param rotating_size_time: 是否同时按「大小 + 时间 + 年龄」管理（推荐）；
        单文件达 maxBytes 立即滚动（数字后缀 .1/.2/...），到每天午夜按时间滚动
        （日期后缀 .2026-07-05）；归档超过 maxAgeDays 天自动删除，归档族总大小
        超过 totalSizeBytes 时按 mtime 从旧到新裁剪
    :param maxBytes: rotating_size_time 下单文件大小上限，默认 500MB
    :param totalSizeBytes: rotating_size_time 下归档族总大小上限，默认 500MB
    :param maxAgeDays: rotating_size_time 下归档最大保留天数，默认 14 天
    :param backupCount: 保留日志文件个数（rotating_size / rotating_time 用）
    :param extra_fmt: 额外的格式化
    :return:
    """

    if name in logging.Logger.manager.loggerDict.keys():
        return logging.getLogger(name)

    logger = logging.getLogger(name)
    level = level.upper()
    logger.setLevel(level)
    logger.propagate = False
    if distributed_rank:
        return logger

    # if settings.DEBUG:
    #     fmt = f"%(asctime)s -> %(levelname)-8s: %(module)-15s | %(lineno)-3d |{extra_fmt}%(message)s"
    # else:
    computer_ip, computer_name = get_host_ip()
    service_name = ProjectSettings.PROJECT_NAME
    fmt = (f'%(asctime)s.%(msecs)03d|'
           f'{computer_ip}|{computer_name}|{service_name}|'
           f'p%(process)d|t%(thread)d|%(levelname)s|{extra_fmt}%(message)s')

    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    if stdout:
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    if stderr:
        err = logging.StreamHandler(stream=sys.stderr)
        err.setLevel(level)
        err.setFormatter(formatter)
        logger.addHandler(err)

    if socket:
        socketHandler = handlers.SocketHandler('localhost', logging.handlers.DEFAULT_TCP_LOGGING_PORT)
        socketHandler.setLevel(level)
        socketHandler.setFormatter(formatter)
        logger.addHandler(socketHandler)

    if save or filename:
        if filename is None:
            filename = time.strftime("%Y-%m-%d_%H.%M.%S", time.localtime()) + ".log"

        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), exist_ok=True)

        if rotating_time:
            # 每 1(interval) 天(when) 重写1个文件,保留7(backupCount) 个旧文件；when还可以是Y/m/H/M/S
            th = TimedRotatingFileHandler(filename, when='D', interval=1, backupCount=backupCount, encoding="UTF-8")
            th.setLevel(level)
            th.setFormatter(formatter)
            logger.addHandler(th)

        elif rotating_size:
            # 每 1024Bytes重写一个文件,保留2(backupCount) 个旧文件
            sh = RotatingFileHandler(filename, mode=mode, maxBytes=1024 * 1024, backupCount=backupCount,
                                     encoding="UTF-8")
            sh.setLevel(level)
            sh.setFormatter(formatter)
            logger.addHandler(sh)

        elif rotating_size_time:
            # 按「大小 + 时间 + 年龄」管理：
            #   - 单文件达 maxBytes → 立即滚动为数字后缀归档（.1/.2/...）
            #   - 到每天午夜 → 滚动为日期后缀归档（.2026-07-05）
            #   - 归档超过 maxAgeDays 天 → 自动删除
            #   - 归档族总大小超 totalSizeBytes → 按 mtime 从旧到新裁剪
            sth = SizeTimedRotatingFileHandler(
                filename, mode=mode, maxBytes=maxBytes,
                totalSizeBytes=totalSizeBytes, maxAgeDays=maxAgeDays,
                encoding="UTF-8",
            )
            sth.setLevel(level)
            sth.setFormatter(formatter)
            logger.addHandler(sth)

        else:
            fh = logging.FileHandler(filename, mode=mode, encoding="UTF-8")
            fh.setLevel(level)
            fh.setFormatter(formatter)
            logger.addHandler(fh)

    return logger


_, hostname = get_host_ip()
openclaw_logger = setup_logger(
    name=ProjectSettings.PROJECT_NAME,
    filename=os.path.join(
        f"/{ProjectSettings.LOG_ROOT_DIR}/{ProjectSettings.PROJECT_NAME}/{hostname}/",
        f"{ProjectSettings.PROJECT_NAME}.log"
    ),
    stdout=os.getenv("MCLAW_DEBUG", "0").lower() in ("1", "true", "yes", "on"),
    level="info",
    rotating_size_time=True,
    maxBytes=100 * 1024 * 1024,         # 单文件 100MB 即滚动
    totalSizeBytes=400 * 1024 * 1024,   # 归档族上限 400MB；加单文件 100MB → 总盘 ≈ 500MB
    maxAgeDays=14,
)


def status_log(msg, logger=openclaw_logger, info_dict=None, server_type='API', stdout=False):
    if info_dict is None:
        info_dict = {}
    # 合并全局 info_dict（调用方显式传入值优先）
    try:
        from mclaw.utils.settings import GlobalLogInfoSettings
        merged = {
            'requestId': GlobalLogInfoSettings.REQUEST_ID,
            **info_dict,
        }
    except Exception:
        merged = dict(info_dict)
    showinfo = server_type + "|||"
    showinfo += str(msg) + "|"
    for info_key, info_value in merged.items():
        info = str(info_key) + ":" + str(info_value) + "|"
        showinfo += info
    if "fail" in msg or "error" in msg:
        logger.warning(showinfo)
    elif "内部异常错误" in msg:
        logger.error(showinfo)
    else:
        logger.info(showinfo)

    if stdout:
        print(msg)


def log_runtime_env(logger=openclaw_logger) -> None:
    """``import mclaw`` 时打印一次运行时环境变量（会话 / 工具调用 / 实例标识）。

    这些值在进程内恒定，无需随每条 ``status_log`` 重复——全局只用
    ``requestId`` 做跨条目追踪。本函数在包导入时调用一次，把环境变量上下文
    与本次 ``requestId`` 关联记入日志（落 ``openclaw.log``，不进 stdout），
    便于按 currentSession / toolCallId / sessionId / openclawId 维度排查。

    空值落 ``(unset)`` 保留，明确标识缺失的运行环境。
    """
    status_log(
        '[mclaw]进程启动环境变量',
        logger=logger,
        info_dict={
            'MCLAW_CURRENT_SESSION': (os.getenv('MCLAW_CURRENT_SESSION') or '').strip() or '(unset)',
            'MCLAW_TOOL_CALL_ID': (os.getenv('MCLAW_TOOL_CALL_ID') or '').strip() or '(unset)',
            'MCLAW_SESSION_ID': (os.getenv('MCLAW_SESSION_ID') or '').strip() or '(unset)',
            'OPENCLAW_ID': (os.getenv('OPENCLAW_ID') or '').strip() or '(unset)',
        },
        server_type='MCLAW',
    )
