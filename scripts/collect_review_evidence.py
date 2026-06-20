#!/usr/bin/env python3
"""Review Evidence Collector — 评审证据收集器.

Establishes the "review data must attach actual command output" mechanism.
All review claims must be backed by real command output captured by this script.

Usage:
    python scripts/collect_review_evidence.py [--output OUTPUT_DIR] [--suite SUITE]

Suites:
    all       - Run all evidence suites (default)
    pytest    - Pytest with coverage
    mypy      - Mypy type check
    ruff      - Ruff lint
    frontend  - Frontend lint and build
    security  - Bandit security scan
    structure - Project structure inventory
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "planning" / "review_evidence"


def _now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _run_command(cmd: list[str], cwd: Path, timeout: int = 600) -> dict[str, Any]:
    """Run a command and capture full output.

    Returns a dict with: command, returncode, stdout, stderr, duration_ms.
    Never raises — captures everything for evidence.
    """
    start = _dt.datetime.now()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = f"TIMEOUT after {timeout}s\n" + (
            exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        )
    except Exception as exc:  # noqa: BLE001 — evidence collector must never crash
        returncode = -2
        stdout = ""
        stderr = f"EXECUTION_ERROR: {type(exc).__name__}: {exc}"

    duration_ms = int((_dt.datetime.now() - start).total_seconds() * 1000)
    return {
        "command": " ".join(cmd),
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }


def _write_evidence(
    output_dir: Path,
    suite_name: str,
    evidence: dict[str, Any],
    stamp: str,
) -> Path:
    """Write evidence as both JSON (machine-readable) and Markdown (human-readable)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{stamp}_{suite_name}.json"
    md_path = output_dir / f"{stamp}_{suite_name}.md"

    json_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    lines: list[str] = [
        f"# 评审证据 — {suite_name}",
        "",
        f"- **采集时间**: {evidence['collected_at']}",
        f"- **仓库**: {evidence['repo_root']}",
        f"- **命令**: `{evidence['command']}`",
        f"- **返回码**: {evidence['returncode']}",
        f"- **耗时**: {evidence['duration_ms']} ms",
        "",
        "## stdout",
        "",
        "```",
        evidence["stdout"] or "(empty)",
        "```",
        "",
        "## stderr",
        "",
        "```",
        evidence["stderr"] or "(empty)",
        "```",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def collect_pytest(output_dir: Path, stamp: str) -> list[Path]:
    """Pytest with coverage — the authoritative test evidence."""
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [
        python,
        "-m",
        "pytest",
        "tests/",
        "--cov=src/promiselink",
        "--cov-report=term-missing",
        "--cov-report=json:coverage.json",
        "-q",
        "--tb=short",
    ]
    evidence = _run_command(cmd, REPO_ROOT, timeout=900)
    evidence["collected_at"] = _dt.datetime.now().isoformat()
    evidence["repo_root"] = str(REPO_ROOT)
    paths = [_write_evidence(output_dir, "pytest", evidence, stamp)]

    # Also parse coverage.json if it exists
    cov_json = REPO_ROOT / "coverage.json"
    if cov_json.exists():
        cov_data = json.loads(cov_json.read_text(encoding="utf-8"))
        total = cov_data.get("totals", {})
        cov_evidence = {
            "collected_at": _dt.datetime.now().isoformat(),
            "repo_root": str(REPO_ROOT),
            "command": "(parsed coverage.json)",
            "returncode": 0,
            "stdout": json.dumps(
                {
                    "line_coverage": total.get("percent_covered", 0),
                    "covered_lines": total.get("covered_lines", 0),
                    "num_statements": total.get("num_statements", 0),
                    "missing_lines": total.get("missing_lines", 0),
                    "files": len(cov_data.get("files", {})),
                },
                indent=2,
            ),
            "stderr": "",
            "duration_ms": 0,
        }
        paths.append(_write_evidence(output_dir, "coverage_summary", cov_evidence, stamp))
    return paths


def collect_mypy(output_dir: Path, stamp: str) -> list[Path]:
    """Mypy type check — the authoritative type-check evidence."""
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [python, "-m", "mypy", "src/promiselink", "--ignore-missing-imports"]
    evidence = _run_command(cmd, REPO_ROOT, timeout=600)
    evidence["collected_at"] = _dt.datetime.now().isoformat()
    evidence["repo_root"] = str(REPO_ROOT)
    return [_write_evidence(output_dir, "mypy", evidence, stamp)]


def collect_ruff(output_dir: Path, stamp: str) -> list[Path]:
    """Ruff lint check."""
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [python, "-m", "ruff", "check", "src/", "tests/"]
    evidence = _run_command(cmd, REPO_ROOT, timeout=300)
    evidence["collected_at"] = _dt.datetime.now().isoformat()
    evidence["repo_root"] = str(REPO_ROOT)
    return [_write_evidence(output_dir, "ruff", evidence, stamp)]


def collect_frontend(output_dir: Path, stamp: str) -> list[Path]:
    """Frontend lint and build evidence."""
    paths: list[Path] = []
    frontend_dir = REPO_ROOT / "frontend"

    # Check eslint availability
    eslint_check = _run_command(
        ["npx", "eslint", "--version"], frontend_dir, timeout=60
    )
    eslint_check["collected_at"] = _dt.datetime.now().isoformat()
    eslint_check["repo_root"] = str(frontend_dir)
    paths.append(_write_evidence(output_dir, "frontend_eslint_version", eslint_check, stamp))

    # Run eslint if available
    if eslint_check["returncode"] == 0:
        eslint_run = _run_command(
            ["npx", "eslint", "src/", "--max-warnings=0"], frontend_dir, timeout=300
        )
    else:
        eslint_run = {
            "collected_at": _dt.datetime.now().isoformat(),
            "repo_root": str(frontend_dir),
            "command": "npx eslint src/ --max-warnings=0",
            "returncode": -1,
            "stdout": "",
            "stderr": "SKIPPED: eslint not available (see version check)",
            "duration_ms": 0,
        }
    paths.append(_write_evidence(output_dir, "frontend_eslint_run", eslint_run, stamp))

    # TypeScript check
    tsc_run = _run_command(
        ["npx", "tsc", "--noEmit"], frontend_dir, timeout=300
    )
    tsc_run["collected_at"] = _dt.datetime.now().isoformat()
    tsc_run["repo_root"] = str(frontend_dir)
    paths.append(_write_evidence(output_dir, "frontend_tsc", tsc_run, stamp))

    return paths


def collect_security(output_dir: Path, stamp: str) -> list[Path]:
    """Bandit security scan."""
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [python, "-m", "bandit", "-r", "src/", "-q"]
    evidence = _run_command(cmd, REPO_ROOT, timeout=300)
    evidence["collected_at"] = _dt.datetime.now().isoformat()
    evidence["repo_root"] = str(REPO_ROOT)
    return [_write_evidence(output_dir, "bandit", evidence, stamp)]


def collect_structure(output_dir: Path, stamp: str) -> list[Path]:
    """Project structure inventory — counts of files, lines, modules."""
    src_dir = REPO_ROOT / "src" / "promiselink"
    tests_dir = REPO_ROOT / "tests"

    py_files = list(src_dir.rglob("*.py"))
    test_files = list(tests_dir.rglob("test_*.py"))

    total_lines = sum(
        f.read_text(encoding="utf-8", errors="replace").count("\n") for f in py_files
    )
    test_lines = sum(
        f.read_text(encoding="utf-8", errors="replace").count("\n") for f in test_files
    )

    # Count test functions
    test_func_count = 0
    for tf in test_files:
        content = tf.read_text(encoding="utf-8", errors="replace")
        test_func_count += content.count("def test_")

    structure = {
        "collected_at": _dt.datetime.now().isoformat(),
        "repo_root": str(REPO_ROOT),
        "command": "(structure inventory)",
        "returncode": 0,
        "stdout": json.dumps(
            {
                "src_py_files": len(py_files),
                "src_total_lines": total_lines,
                "test_files": len(test_files),
                "test_total_lines": test_lines,
                "test_functions": test_func_count,
            },
            indent=2,
        ),
        "stderr": "",
        "duration_ms": 0,
    }
    return [_write_evidence(output_dir, "structure", structure, stamp)]


SUITES = {
    "pytest": collect_pytest,
    "mypy": collect_mypy,
    "ruff": collect_ruff,
    "frontend": collect_frontend,
    "security": collect_security,
    "structure": collect_structure,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect review evidence with real command output.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for evidence files.",
    )
    parser.add_argument(
        "--suite",
        default="all",
        choices=["all"] + list(SUITES.keys()),
        help="Evidence suite to collect.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    stamp = _now_stamp()

    suites_to_run = list(SUITES.keys()) if args.suite == "all" else [args.suite]

    print(f"[evidence] Collecting evidence to: {output_dir}")
    print(f"[evidence] Stamp: {stamp}")
    print(f"[evidence] Suites: {suites_to_run}")
    print()

    all_paths: list[Path] = []
    for suite_name in suites_to_run:
        print(f"[evidence] Running suite: {suite_name}")
        collector = SUITES[suite_name]
        try:
            paths = collector(output_dir, stamp)
            all_paths.extend(paths)
            for p in paths:
                print(f"  -> {p.relative_to(REPO_ROOT)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {type(exc).__name__}: {exc}")

    # Write index
    index_path = output_dir / f"{stamp}_INDEX.md"
    index_lines = [
        f"# 评审证据索引 — {stamp}",
        "",
        f"采集时间: {_dt.datetime.now().isoformat()}",
        f"仓库: {REPO_ROOT}",
        "",
        "## 证据文件清单",
        "",
        "| Suite | 文件 |",
        "|-------|------|",
    ]
    for p in all_paths:
        rel = p.relative_to(REPO_ROOT)
        index_lines.append(f"| {p.stem.replace(f'{stamp}_', '')} | `{rel}` |")
    index_lines.extend(["", "## 使用说明", "", "本目录下所有文件均为实际命令输出，作为评审证据。"])
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    print(f"\n[evidence] Index: {index_path.relative_to(REPO_ROOT)}")
    print(f"[evidence] Total evidence files: {len(all_paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
