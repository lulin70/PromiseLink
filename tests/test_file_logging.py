"""文件日志回归测试（⑥ / L-18，2026-09-21）。

背景：桌面端此前**只有 stdout 一个日志出口**（``PrintLoggerFactory()``，无任何
``FileHandler``），终端窗口一关日志即永久丢失。而 ⑥ 要把 ``promiselink.spec``
改成 ``console=False``（窗口化，不再有终端窗口）—— 若不同时补上文件日志，
"排障能力"不是下降而是**归零**。故本文件锁死三件事：

1. 打包运行必须把日志落到 ``~/.promiselink/logs/promiselink.log``
2. uvicorn 的启动失败栈（走 stdlib、默认 propagate=False）也必须进这个文件
3. 源码运行 / 测试**不得**往开发者 HOME 写文件（避免污染）

每条断言都配一个反向探针用例，确保"真通过"而不是"没跑到"。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import structlog

from promiselink.core.logging import _LogFileSink, configure_logging, get_logger

_LOG_NAME = "promiselink.log"


@pytest.fixture(autouse=True)
def _restore_logging_state():
    """还原全局日志状态，避免用例之间互相污染（handler 泄漏会写出重复行）。"""
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level
    propagate_before = {n: logging.getLogger(n).propagate for n in ("uvicorn", "uvicorn.error")}

    yield

    for handler in list(root.handlers):
        if handler not in handlers_before:
            root.removeHandler(handler)
            if isinstance(handler, _LogFileSink):
                handler.close()
    root.setLevel(level_before)
    for name, value in propagate_before.items():
        logging.getLogger(name).propagate = value
    structlog.reset_defaults()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_file_log_written_when_log_dir_given(tmp_path: Path):
    """显式给出 log_dir 时必须真的落盘，且含启动日志行。"""
    configure_logging(json_output=False, log_dir=tmp_path)
    get_logger().info("promiselink_starting")

    log_file = tmp_path / _LOG_NAME
    assert log_file.exists(), "给出 log_dir 后未生成日志文件"
    assert "promiselink_starting" in _read(log_file)


def test_frozen_run_uses_runtime_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """打包运行（sys.frozen）默认写到 ~/.promiselink/logs，无需任何显式配置。"""
    import promiselink.config as config

    monkeypatch.setattr(config, "_PROMISELINK_HOME", tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    configure_logging(json_output=False)
    get_logger().info("packaged_startup_probe")

    log_file = tmp_path / "logs" / _LOG_NAME
    assert log_file.exists(), "打包运行未按 runtime_log_dir() 落盘"
    assert "packaged_startup_probe" in _read(log_file)


def test_source_run_writes_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """反向探针的一侧：源码运行不得创建日志目录 / 挂文件 handler。

    否则开发机与 CI runner 的 HOME 会被静默写入文件（CI 上还会拖慢每个用例）。
    """
    import promiselink.config as config

    monkeypatch.setattr(config, "_PROMISELINK_HOME", tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)

    configure_logging(json_output=False)

    assert not (tmp_path / "logs").exists(), "源码运行竟然创建了日志目录"
    assert not [h for h in logging.getLogger().handlers if isinstance(h, _LogFileSink)]


def test_uvicorn_traceback_is_captured_in_file(tmp_path: Path):
    """⑥ 的崩溃探针：窗口化后终端没了，uvicorn 的失败栈只能靠文件日志带出来。

    uvicorn 的 logger 默认 ``propagate=False``（自己写 stderr），故
    ``_attach_file_logging`` 显式放开 propagate —— 这条断言就是它的验收条件。
    """
    configure_logging(json_output=False, log_dir=tmp_path)

    try:
        raise RuntimeError("boom-crash-probe")
    except RuntimeError:
        logging.getLogger("uvicorn.error").error("Application startup failed", exc_info=True)

    text = _read(tmp_path / _LOG_NAME)
    assert "Application startup failed" in text
    assert "boom-crash-probe" in text, "异常消息未进文件日志"
    assert "Traceback" in text, "栈未进文件日志 —— 崩溃后仍然拿不到证据"


def test_probe_uvicorn_propagate_false_loses_the_traceback(tmp_path: Path):
    """上一条的反向探针：把 propagate 复原为 False，断言必须失效。"""
    configure_logging(json_output=False, log_dir=tmp_path)
    logging.getLogger("uvicorn.error").propagate = False

    try:
        raise RuntimeError("boom-crash-probe")
    except RuntimeError:
        logging.getLogger("uvicorn.error").error("Application startup failed", exc_info=True)

    log_file = tmp_path / _LOG_NAME
    # 文件可能压根不存在（delay=True，只有 stdlib 记录才会开文件）—— 这本身就是
    # 探针生效的证据，故两种情形都判"没进文件"。
    text = _read(log_file) if log_file.exists() else ""
    assert "boom-crash-probe" not in text, "探针失效：propagate=False 时不该进文件"


def test_stdlib_records_land_in_file(tmp_path: Path):
    """应用内其它 stdlib 日志同样要进文件（不只 structlog 与 uvicorn）。"""
    configure_logging(log_level="INFO", json_output=False, log_dir=tmp_path)
    logging.getLogger("promiselink.submodule").warning("stdlib-warning-probe")

    assert "stdlib-warning-probe" in _read(tmp_path / _LOG_NAME)


def test_repeated_configure_does_not_duplicate_lines(tmp_path: Path):
    """lifespan 会被反复进出（含 TestClient 用例）：重申配置不得叠加 handler。"""
    configure_logging(json_output=False, log_dir=tmp_path)
    configure_logging(json_output=False, log_dir=tmp_path)
    get_logger().info("only-once-probe")

    assert _read(tmp_path / _LOG_NAME).count("only-once-probe") == 1


def test_rotation_produces_backup_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """structlog 的写入绕过 ``emit()``，轮转必须靠 ``_LogFileSink.write`` 自己补。

    不设这条断言的话，日志文件会无上限增长到把用户磁盘写满。
    """
    from promiselink.core import logging as pl_logging

    monkeypatch.setattr(pl_logging, "_LOG_MAX_BYTES", 300)
    configure_logging(json_output=False, log_dir=tmp_path)

    logger = get_logger()
    for i in range(50):
        logger.info("rotation-probe", seq=i)

    assert (tmp_path / _LOG_NAME).exists()
    backups = list(tmp_path.glob(f"{_LOG_NAME}.*"))
    assert backups, "只写 structlog 时未触发轮转（写入路径漏了大小检查）"


def test_unwritable_log_dir_does_not_block_startup(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """日志目录不可写时应用必须照常启动（诊断能力不是启动前置条件）。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    configure_logging(json_output=False, log_dir=blocker / "logs")

    assert not [h for h in logging.getLogger().handlers if isinstance(h, _LogFileSink)]
    get_logger().info("still-alive-probe")
    assert "still-alive-probe" in capsys.readouterr().out
