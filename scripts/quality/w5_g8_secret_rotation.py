"""
W5 G8 — Secret 轮换演练（staging 模拟）

目的：在不动生产配置的前提下，验证 W5 关键 secret 轮换路径：
- HMAC key v1 轮换：旧 secret 下签发的 token 在新 secret 下立即失效（fail-closed）
- DB credential：仅做配置 reload 模拟（切 DATABASE_URL，验证新 DB 可建表/查表）

不执行：
- 不修改生产 secret（仅在本脚本局部 monkeypatch settings）
- 不 push / release / deployment
- 不修改 §3 锁定契约
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "e2e_evidence" / "w5_g8_secret_rotation"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _scenario_hmac_rotation() -> dict[str, object]:
    """A. HMAC key rotation：
       - 用 v1 secret 签发 token，v1 verify 通过
       - 把 settings.candidate_token_secret_v1 换成新值（模拟轮换完成）
       - 旧 token 必须 fail-closed（HMAC 不再匹配）
       - 用新 secret 签发的 token 在新 secret 下 verify 通过
    """
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    os.environ["CANDIDATE_TOKEN_SECRET_V1"] = "synthetic-w5-v1-original-for-g8"

    from promiselink.config import get_settings
    from promiselink.core.auth import issue_candidate_token, verify_candidate_token
    from promiselink.core.exceptions import CandidateTokenError

    settings = get_settings()
    settings.candidate_token_key_version = "1"

    # 1. v1 secret 下签发 + verify 通过
    token_v1, _ = issue_candidate_token(
        user_id="00000000-0000-4000-8000-00000000a501",
        event_id="00000000-0000-4000-8000-000000000111",
        scope_type="entity",
        resource_id="00000000-0000-4000-8000-000000000222",
        candidate_digest="0" * 64,
        operation_key="op-g8-a",
        resolver_version="r1", score_version="s1", embedding_space="default",
    )
    ok_v1_under_v1 = bool(verify_candidate_token(
        token_v1, authenticated_user_id="00000000-0000-4000-8000-00000000a501",
        event_id="00000000-0000-4000-8000-000000000111",
        scope_type="entity",
        extracted_entity_id="00000000-0000-4000-8000-000000000222",
    ))

    # 2. 模拟轮换：把 v1 secret 换成新值（生产上等价于 secret manager 推新 key）
    settings.candidate_token_secret_v1 = "synthetic-w5-v1-ROTATED-for-g8"

    rejected_old = False
    try:
        verify_candidate_token(
            token_v1, authenticated_user_id="00000000-0000-4000-8000-00000000a501",
            event_id="00000000-0000-4000-8000-000000000111",
            scope_type="entity",
            extracted_entity_id="00000000-0000-4000-8000-000000000222",
        )
    except CandidateTokenError:
        rejected_old = True

    # 3. 用新 secret 重新签发 + verify
    token_v2, _ = issue_candidate_token(
        user_id="00000000-0000-4000-8000-00000000a501",
        event_id="00000000-0000-4000-8000-000000000111",
        scope_type="entity",
        resource_id="00000000-0000-4000-8000-000000000222",
        candidate_digest="0" * 64,
        operation_key="op-g8-b",
        resolver_version="r1", score_version="s1", embedding_space="default",
    )
    ok_v2_under_v2 = bool(verify_candidate_token(
        token_v2, authenticated_user_id="00000000-0000-4000-8000-00000000a501",
        event_id="00000000-0000-4000-8000-000000000111",
        scope_type="entity",
        extracted_entity_id="00000000-0000-4000-8000-000000000222",
    ))

    return {
        "scenario": "A_hmac_key_rotation",
        "v1_token_verify_under_v1": ok_v1_under_v1,
        "old_token_rejected_after_rotation": rejected_old,
        "v2_token_verify_under_v2": ok_v2_under_v2,
        "result": "pass" if (ok_v1_under_v1 and rejected_old and ok_v2_under_v2) else "fail",
    }


def _scenario_db_credential_reload() -> dict[str, object]:
    """B. DB credential 轮换（模拟）：切到新 DATABASE_URL，跑 alembic upgrade head，
    验证关键表存在；等价于生产上切换连接串后跑迁移。"""
    import subprocess
    new_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
    new_db_url = f"sqlite:///{new_db}"
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    env = os.environ.copy()
    env["DATABASE_URL"] = new_db_url
    proc = subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        return {
            "scenario": "B_db_credential_reload",
            "new_db_path": new_db,
            "alembic_rc": proc.returncode,
            "stderr_tail": proc.stderr[-500:],
            "result": "fail",
        }

    from sqlalchemy import create_engine, inspect
    sync_url = new_db_url.replace("+aiosqlite", "")
    eng = create_engine(sync_url)
    insp = inspect(eng)
    tables = sorted(t for t in insp.get_table_names() if t != "alembic_version")
    eng.dispose()

    # 以 B-8 schema_parity_proxy.base_create_all 已校验的 11 张表为权威清单
    # （来源：docs/e2e_evidence/w5_parity/manifest.json）
    expected = (
        "associations", "entities", "entity_corrections", "events",
        "relationship_briefs", "reminder_logs", "reminder_preferences",
        "scheduled_events", "score_audit_logs", "snooze_schedules", "todos",
    )
    has_critical = all(t in tables for t in expected)
    return {
        "scenario": "B_db_credential_reload",
        "new_db_path": new_db,
        "alembic_rc": proc.returncode,
        "tables_after_reload": len(tables),
        "tables_actual": tables,
        "expected_match_b8_parity": has_critical,
        "expected_count": len(expected),
        "result": "pass" if has_critical else "fail",
    }


def main() -> int:
    t0 = time.time()
    a = _scenario_hmac_rotation()
    b = _scenario_db_credential_reload()

    report = {
        "schema_version": "w5-secret-rotation-v1",
        "drilled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": [a, b],
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    overall = all(s["result"] == "pass" for s in (a, b))
    report["overall"] = "pass" if overall else "fail"

    out_path = EVIDENCE_DIR / "manifest.json"
    with out_path.open("w", encoding="utf-8") as fh:
        import json
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"G8 secret rotation drill: {report['overall']} → {out_path}")
    return 0 if overall else 4


if __name__ == "__main__":
    raise SystemExit(main())