#!/usr/bin/env python3
"""文档版本一致性门禁（③，2026-09-21）。

为什么需要：README 三语的「文档版本」行与文档链接长期停留在 PRD v5.8，而
``docs/spec/PRD_v1.md`` 头部早已是 v5.9 —— README 是用户的第一印象，声称的
版本与文档实际版本不一致，属对外口径错误。本门禁把「README 声称的版本 ==
文档头部声明的版本」变成**可重复执行**的检查（CI 与本地同一份代码）。

刻意**不**检查的两类行（是历史事实，不是漂移，回填反而丢失可追溯性）：
  * README 里程碑段里的 ``PRD v5.2`` / ``技术设计 v3.2``（当时交付所依据的版本）
  * 技术设计头部的 ``对应PRD: v5.2``（写作基线，口径见该文件的「口径说明」）

用法：``python scripts/quality/check_doc_versions.py [仓库根目录]``
退出码：0 = 一致；1 = 有不一致（逐条打印明细）
"""

from __future__ import annotations

import pathlib
import re
import sys

# README 三语的「文档版本」行标签
_VERSION_ROW = re.compile(r"(文档版本|Documentation version|ドキュメントバージョン)")
# 版本行内的两条声称
_ROW_PRD = re.compile(r"PRD\s+(v?\d+\.\d+)")
_ROW_TECH = re.compile(r"(?:Tech|技术设计|技術設計)\s+(v?\d+\.\d+)")
# 文档链接行（只在指向真实文档的链接上取版本，里程碑段不匹配）
_PRD_LINK = re.compile(r"\[PRD\s+v?(\d+\.\d+)\]\(docs/spec/PRD_v1\.md\)")
_TECH_LINK = re.compile(r"\[(?:技术设计|Technical Design|技術設計)\s+v?(\d+\.\d+)\]\(docs/architecture/")
# 文档头部声明的版本（唯一事实来源）
_HEADER_VERSION = re.compile(r"^>\s*\*\*版本\*\*:\s*v?(\d+\.\d+)", re.M)

_READMES = ("README.md", "README.en.md", "README.jp.md")


def _norm(version: str) -> str:
    return version.lstrip("v")


def _header_version(path: pathlib.Path) -> str:
    match = _HEADER_VERSION.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"::error::{path} 头部找不到 `> **版本**: vX.Y`，门禁无法判定")
    return _norm(match.group(1))


def _claims(root: pathlib.Path) -> list[tuple[str, int, str, str]]:
    """收集 README 里的版本声称：(文件, 行号, 类别, 版本)。"""
    found: list[tuple[str, int, str, str]] = []
    for name in _READMES:
        path = root / name
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _VERSION_ROW.search(line):
                for kind, pattern in (("PRD", _ROW_PRD), ("Tech", _ROW_TECH)):
                    match = pattern.search(line)
                    if match is not None:
                        found.append((name, lineno, kind, _norm(match.group(1))))
            for match in _PRD_LINK.finditer(line):
                found.append((name, lineno, "PRD", _norm(match.group(1))))
            for match in _TECH_LINK.finditer(line):
                found.append((name, lineno, "Tech", _norm(match.group(1))))
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = pathlib.Path(args[0]) if args else pathlib.Path(".")

    actual = {
        "PRD": _header_version(root / "docs/spec/PRD_v1.md"),
        "Tech": _header_version(root / "docs/architecture/PromiseLink_技术设计_v1.md"),
    }
    print(f"文档实际版本：PRD v{actual['PRD']} / 技术设计 v{actual['Tech']}")

    claims = _claims(root)
    if not claims:
        print("::error::README 三语里一条版本声称都没找到，门禁形同虚设（选择器可能已失效）")
        return 1

    problems = [
        f"{name}:{lineno} 声称 {kind} v{claimed}，文档实际 v{actual[kind]}"
        for name, lineno, kind, claimed in claims
        if claimed != actual[kind]
    ]
    for name, lineno, kind, claimed in claims:
        mark = "✓" if claimed == actual[kind] else "✗"
        print(f"  {mark} {name}:{lineno} {kind} v{claimed}")

    if problems:
        for item in problems:
            print(f"::error::文档版本不一致 —— {item}")
        return 1

    print(f"✓ README 三语共 {len(claims)} 条版本声称与文档头部一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
