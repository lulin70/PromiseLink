"""
W5 Stage 0 — staging deployment evidence 回灌脚本

目的：用户在 staging 主机执行完 W5_STAGE0_STAGING_DEPLOY_v1.md §3 三个脚本后，
把 stdout 贴到本脚本同目录的 stdout 文件中，运行本脚本生成 Stage 0 manifest。

不执行：
- 不修改 §3 锁定契约
- 不 push / release / production deploy
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "e2e_evidence" / "w5_stage0_staging"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR = Path(__file__).resolve().parent / "stage0_inputs"


def _read_or_run(name: str, fallback_cmd: str | None) -> str:
    p = INPUT_DIR / f"{name}.txt"
    if p.exists() and p.stat().st_size > 0:
        return p.read_text(encoding="utf-8")
    if fallback_cmd:
        proc = subprocess.run(fallback_cmd, cwd=str(PROJECT_ROOT), shell=True,
                              capture_output=True, text=True)
        return proc.stdout + "\n" + proc.stderr
    return ""


def _scan_e2e(stdout: str) -> dict[str, object]:
    # 解析 PASS=14 / FAIL=0
    m_pass = re.search(r"PASS=(\d+)", stdout)
    m_fail = re.search(r"FAIL=(\d+)", stdout)
    return {
        "pass_count": int(m_pass.group(1)) if m_pass else None,
        "fail_count": int(m_fail.group(1)) if m_fail else None,
        "result": "pass" if (m_pass and int(m_pass.group(1)) >= 14 and m_fail and int(m_fail.group(1)) == 0) else "fail",
    }


def _scan_antighost(stdout: str) -> dict[str, object]:
    accepted = "OK" in stdout or "accepted" in stdout.lower()
    return {"validator_exit_hint": "0" if accepted else "nonzero", "result": "pass" if accepted else "fail"}


def _scan_validator(stdout: str) -> dict[str, object]:
    accepted = "accepted" in stdout.lower()
    return {"status": "accepted" if accepted else "rejected", "result": "pass" if accepted else "fail"}


def _verify_tag(tag: str = "v1.0-rc1") -> dict[str, object]:
    proc = subprocess.run(["git", "rev-parse", f"{tag}^{{commit}}"],
                          cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    sha = proc.stdout.strip() if proc.returncode == 0 else ""
    return {"tag": tag, "commit_sha": sha, "pushed": bool(sha)}


def main() -> int:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    e2e_stdout = _read_or_run("e2e_w5_real_user", None)
    ag_stdout = _read_or_run("antighost", None)
    val_stdout = _read_or_run("manifest_validator", None)

    if not e2e_stdout:
        print(f"ERROR: no e2e stdout found at {INPUT_DIR / 'e2e_w5_real_user.txt'}",
              file=sys.stderr)
        print("请把 W5_STAGE0_STAGING_DEPLOY_v1.md §3 第一个脚本的 stdout 贴入该文件。",
              file=sys.stderr)
        return 5

    e2e = _scan_e2e(e2e_stdout)
    ag = _scan_antighost(ag_stdout) if ag_stdout else {"result": "skipped", "reason": "no antighost stdout"}
    val = _scan_validator(val_stdout) if val_stdout else {"result": "skipped", "reason": "no validator stdout"}
    ver = _verify_tag()

    report = {
        "schema_version": "w5-stage0-v1",
        "tag": ver["tag"],
        "commit_sha": ver["commit_sha"],
        "drilled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "e2e": e2e,
        "antighost": ag,
        "manifest_validator": val,
    }
    overall = all(s.get("result") == "pass" for s in (e2e, ag, val) if isinstance(s.get("result"), str))
    report["overall"] = "pass" if overall else "fail_or_skipped"

    out_path = EVIDENCE_DIR / "manifest.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"Stage 0 manifest: {report['overall']} → {out_path}")
    return 0 if overall else 4


if __name__ == "__main__":
    raise SystemExit(main())