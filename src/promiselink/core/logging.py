"""Structured logging configuration for PromiseLink.

Architecture Design §8.0.7 — 7-role review P0 gap fix.
Uses structlog for JSON structured output with request_id propagation.

⑥ / L-18（2026-09-21）：新增文件日志。此前桌面端**只有 stdout 一个出口**
（``PrintLoggerFactory()``），终端窗口一关日志即永久丢失 —— 而最需要日志的
非技术用户恰恰不读终端，售后因此拿不到任何证据。文件日志是 ``console=False``
（窗口化）的前置条件：没有它，"排障能力"不是下降，而是归零。
"""

import logging
import logging.handlers
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

import structlog

# 文件日志的轮转策略：单文件 5MB、保留 3 份备份
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3
_LOG_FILE_NAME = "promiselink.log"

# Context variables for request-scoped data
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


class _LogFileSink(logging.handlers.RotatingFileHandler):
    """既是 stdlib 的 ``RotatingFileHandler``，又是 structlog 的行式落点。

    为什么必须"既…又…"：structlog 用 ``PrintLoggerFactory`` 直接写文件对象、
    **不经过 stdlib**，所以它的输出不会走 handler 的 ``emit()``；而 uvicorn 等
    库走 stdlib，必须由 handler 承担。把同一个 handler 同时当文件对象用，两类
    日志才落进**同一个文件、共用同一套轮转策略** —— 若改成两个 handler 各持一个
    句柄写同一文件，轮转时会把对方的句柄写死（写进已被 rename 的旧文件）。
    """

    def write(self, text: str) -> None:
        """structlog 的行式写入（``print(..., file=...)`` 会带上换行）。"""
        self.acquire()
        try:
            if self.stream is None:
                self.stream = self._open()
            self.stream.write(text)
            # structlog 的写入绕过了 emit()，轮转判据必须在这里自己补上，
            # 否则只写 structlog 的日志文件会无上限增长。
            if self.maxBytes and self.stream.tell() >= self.maxBytes:
                self.doRollover()
        finally:
            self.release()

    def flush(self) -> None:
        super().flush()


class _TeeFile:
    """把 structlog 渲染后的整行同时写给终端与文件日志。

    保留终端输出是刻意的：源码运行 / 前台调试的输出与改动前**完全一致**，
    文件日志只是"多一个出口"，不是"换一个出口"。
    """

    def __init__(self, *files: Any) -> None:
        self._files = files

    def write(self, text: str) -> None:
        for f in self._files:
            f.write(text)

    def flush(self) -> None:
        for f in self._files:
            f.flush()


def _attach_file_logging(log_level: str, log_dir: Path) -> _LogFileSink | None:
    """挂上文件日志，返回可同时供 structlog 使用的落点；不可用时返回 None。

    日志目录不可写（权限 / 只读盘）**不得阻止应用启动** —— 用户要的是能用，
    不是把诊断能力当作启动前置条件。
    """
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        sink = _LogFileSink(
            log_dir / _LOG_FILE_NAME,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
    except OSError as exc:
        print(f"[logging] 无法启用文件日志（{log_dir}）：{exc}", file=sys.stderr)
        return None

    sink.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    sink.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    root_logger = logging.getLogger()
    # 幂等：lifespan 会被反复进出（含测试），重复挂 handler 会写出重复行并泄漏 fd。
    for existing in list(root_logger.handlers):
        if isinstance(existing, _LogFileSink):
            root_logger.removeHandler(existing)
            existing.close()
    root_logger.addHandler(sink)

    # uvicorn 的 logger 默认 propagate=False，其"启动失败"栈只进 stderr；
    # 窗口化（console=False）后 stderr 无处可看，故让它们一并落进文件。
    # access 日志刻意不放行：它只描述请求，量大且对售后定位无帮助。
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).propagate = True

    return sink


def configure_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    log_dir: str | Path | None = None,
) -> None:
    """Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, output JSON format; otherwise console format.
        log_dir: 文件日志目录。默认 None → **仅在打包运行**时写
            ``~/.promiselink/logs``；源码运行 / 测试不写文件，避免污染开发者
            HOME 与 CI 环境。显式传入则强制启用。
    """
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    if log_dir is None and getattr(sys, "frozen", False):
        from promiselink.config import runtime_log_dir

        log_dir = runtime_log_dir()

    sink = _attach_file_logging(log_level, Path(log_dir)) if log_dir is not None else None

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=(
            structlog.PrintLoggerFactory(file=_TeeFile(sys.stdout, sink))
            if sink is not None
            else structlog.PrintLoggerFactory()
        ),
        cache_logger_on_first_use=True,
    )

    # Set root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str = "promiselink") -> structlog.stdlib.BoundLogger:
    """Get a structured logger with module name binding.

    Args:
        name: Module name for the logger.

    Returns:
        A bound structlog logger instance.
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def new_request_id() -> str:
    """Generate a new request ID and set it in context.

    Returns:
        The generated request ID.
    """
    req_id = str(uuid.uuid4())
    request_id_var.set(req_id)
    return req_id