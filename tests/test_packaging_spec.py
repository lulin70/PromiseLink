"""打包配置回归测试：promiselink.spec 写进 Info.plist 的版本号与 Bundle ID。

L-12（2026-09-21）：``BUNDLE()`` 未传 ``version=`` / ``bundle_identifier=`` 时，
PyInstaller 会静默使用默认值 —— ``CFBundleShortVersionString="0.0.0"``、
``CFBundleIdentifier=<appname>``。实测 v1.1.1 的 dmg：

    plutil -p PromiseLink.app/Contents/Info.plist
    "CFBundleIdentifier" => "PromiseLink"
    "CFBundleShortVersionString" => "0.0.0"

用户在访达「显示简介」看到的就是 0.0.0，无法判断装的是哪一版；售后排查与
"该升级了"的引导都失去依据（应用内版本号一直正常，来自 ``__init__.py``）。

本文件只做**静态断言**（不执行 PyInstaller 构建），用于防止后续改动把这两个
关键字删掉或把版本号改回硬编码，从而静默退回 0.0.0。
"""

from __future__ import annotations

import ast
from pathlib import Path

import promiselink

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "promiselink.spec"


def _bundle_call() -> ast.Call:
    """Return the ``BUNDLE(...)`` call node from the spec file."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "BUNDLE"
        ):
            return node
    raise AssertionError("promiselink.spec 中找不到 BUNDLE(...) 调用")


def test_bundle_sets_version_and_bundle_identifier():
    """BUNDLE 必须显式传 version= 与 bundle_identifier=，否则静默退回默认值（L-12）。"""
    kwargs = {kw.arg for kw in _bundle_call().keywords}
    assert "version" in kwargs, "BUNDLE 未传 version= → Info.plist 会退回 0.0.0"
    assert "bundle_identifier" in kwargs, "BUNDLE 未传 bundle_identifier= → 退回 appname"


def _names_bound_to_version_path(tree: ast.AST) -> set[str]:
    """Module-level names assigned from an expression mentioning 'VERSION'."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(sub, ast.Constant) and "VERSION" in str(sub.value)
            for sub in ast.walk(node.value)
        ):
            continue
        names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _reads_version_file(call: ast.Call, bound_names: set[str]) -> bool:
    """Whether ``open(...)`` opens the VERSION file (directly or via a bound name)."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "open"):
        return False
    for arg in call.args:
        if isinstance(arg, ast.Name) and arg.id in bound_names:
            return True
        if any(
            isinstance(sub, ast.Constant) and "VERSION" in str(sub.value)
            for sub in ast.walk(arg)
        ):
            return True
    return False


def _version_kwarg() -> ast.keyword:
    """Return the ``version=`` keyword, failing with a readable message if absent."""
    kwargs = {kw.arg: kw for kw in _bundle_call().keywords}
    assert "version" in kwargs, "BUNDLE 未传 version= → Info.plist 会退回 0.0.0"
    return kwargs["version"]


def test_bundle_version_comes_from_the_version_file():
    """version= 的值必须取自仓库根 ``VERSION`` 文件，而不是硬编码字面量。"""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    version_kw = _version_kwarg()
    assert isinstance(version_kw.value, ast.Name), (
        "version= 应是变量（内容来自 VERSION 文件）；硬编码会与 CI 的版本一致性门禁漂移"
    )
    var = version_kw.value.id
    bound_names = _names_bound_to_version_path(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(
            isinstance(item.context_expr, ast.Call)
            and _reads_version_file(item.context_expr, bound_names)
            for item in node.items
        ):
            continue
        if any(
            isinstance(sub, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == var for t in sub.targets)
            for sub in ast.walk(node)
        ):
            return
    raise AssertionError(f"'{var}' 并非从 VERSION 文件读出，无法保证打包版本号正确")


def test_version_file_value_matches_package_version():
    """即将写入 Info.plist 的值（VERSION 文件内容）必须与包自报版本一致。"""
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == promiselink.__version__


def exe_console_value(source: str) -> bool:
    """Return the ``console=`` literal from the spec's ``EXE(...)`` call."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "EXE"
        ):
            for kw in node.keywords:
                if kw.arg == "console":
                    assert isinstance(kw.value, ast.Constant)
                    return bool(kw.value.value)
            raise AssertionError("EXE(...) 未传 console= → 退回 PyInstaller 默认值")
    raise AssertionError("promiselink.spec 中找不到 EXE(...) 调用")


def test_exe_is_windowed_and_keeps_traceback_flag():
    """⑥ / L-16：必须是 ``console=False``（否则 Info.plist 带 ``LSBackgroundOnly=true``）。

    PyInstaller 6.21.0 源码：``if self.console: info_plist_dict['LSBackgroundOnly'] = True``
    —— 即 ``console=True`` 会顺带把应用扔进"后台进程"，Dock 无图标、不参与
    Cmd-Tab；而它同时又保留黑底终端窗口，等于"两者的缺点都要"。

    本项的前提是**已有文件日志**（见 ``tests/test_file_logging.py``）：窗口化会
    让终端窗口消失，没有文件日志就等于把排障能力归零。
    """
    assert exe_console_value(SPEC.read_text(encoding="utf-8")) is False, (
        "EXE(console=True) 会写入 LSBackgroundOnly=true：应用不进 Dock、无法 Cmd-Tab"
    )


def test_probe_console_true_is_flagged():
    """反向探针：把 spec 改回 ``console=True``，上面的门禁必须变红。"""
    regressed = SPEC.read_text(encoding="utf-8").replace("console=False,", "console=True,")
    assert regressed != SPEC.read_text(encoding="utf-8"), "探针未生效：spec 中找不到 console=False,"
    assert exe_console_value(regressed) is True
