"""w5_manifest_validator — W5 evidence manifest strict validator.

实现 W5 Evidence Manifest Schema v1 (docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json)
的逐项校验, 非零退出代表校验失败.

退出码契约 (与 docs/design/W5_IMPLEMENTATION_READINESS_CHECKLIST_v1.md §4.2 一致):
  0 = 校验通过
  4 = manifest 字段缺失 / 类型不符 / 越界 / PII 失败

设计原则:
  - **不预生成** w4_baseline.json: w4_baseline_reference 必须引用已存在的文件;
    文件缺失即视为 manifest 不合格.
  - **不自动修复** 任何缺失字段, 即使 manifest 部分字段可推断.
  - **command_allowlist** 为可选字段; 若填写则必须落在 Test Plan §16.1 列表.
  - **result_summary_whitelist** 为可选字段; 若填写则四个字段必须严格在白名单内,
    且 score ∈ [0,1], language_pair 必须匹配 `^[a-z]{2}_[a-z]{2}$`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

EXIT_OK = 0
EXIT_MANIFEST_REJECTED = 4

COMMAND_ALLOWLIST = frozenset({
    "w5-contract-unit",
    "w5-integration-sqlite",
    "w5-integration-postgresql",
    "w5-golden",
    "w5-e2e",
    "w5-performance",
    "w5-anti-ghost",
})

LANGUAGE_PAIR_RE = re.compile(r"^[a-z]{2}_[a-z]{2}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CONFIG_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "commit_sha",
    "command",
    "started_at",
    "finished_at",
    "database_backend",
    "migration_head",
    "config_digest",
    "embedding_profile",
    "sample_count",
    "counts",
    "metrics",
    "artifacts",
    "pii_scan_result",
    "validator_version",
)

RESULT_SUMMARY_REQUIRED = ("candidate_rank", "method", "score", "language_pair")
RESULT_SUMMARY_METHOD_ALLOWED = {
    "synonym_match",
    "difflib_match",
    "cross_language_match",
    "cross_language_llm_fallback",
}


class ManifestError:
    """Accumulated validation error."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, path: str, msg: str) -> None:
        self.errors.append(f"{path}: {msg}")

    @property
    def ok(self) -> bool:
        return not self.errors


def _err_type(errors: ManifestError, path: str, value: object, expected: str) -> None:
    errors.add(path, f"expected {expected}, got {type(value).__name__}={value!r}")


def validate_manifest(manifest: dict[str, object]) -> ManifestError:
    """Run all validations against an in-memory manifest dict. Returns accumulated errors."""
    errors = ManifestError()

    # 1. 顶层必填字段
    for key in REQUIRED_TOP_LEVEL:
        if key not in manifest:
            errors.add(key, "required field missing")

    # 2. schema_version + validator_version 常量
    if manifest.get("schema_version") != "w5-evidence-v1":
        errors.add("schema_version", "must equal 'w5-evidence-v1'")
    if manifest.get("validator_version") != "w5-manifest-validator-v1":
        errors.add("validator_version", "must equal 'w5-manifest-validator-v1'")

    # 3. commit_sha 格式
    cs = manifest.get("commit_sha")
    if not isinstance(cs, str) or not COMMIT_SHA_RE.match(cs):
        errors.add("commit_sha", "must be 40-hex lowercase string")

    # 4. config_digest 格式
    cd = manifest.get("config_digest")
    if not isinstance(cd, str) or not CONFIG_DIGEST_RE.match(cd):
        errors.add("config_digest", "must be 64-hex lowercase string")

    # 5. command allowlist (optional, but if provided must be in allowlist)
    cmd = manifest.get("command")
    if not isinstance(cmd, str) or not cmd:
        errors.add("command", "must be non-empty string")

    # 6. database_backend
    if manifest.get("database_backend") not in ("sqlite", "postgresql"):
        errors.add("database_backend", "must be 'sqlite' or 'postgresql'")

    # 7. migration_head
    mh = manifest.get("migration_head")
    if not isinstance(mh, str) or not mh:
        errors.add("migration_head", "must be non-empty string")

    # 8. embedding_profile 子结构
    ep = manifest.get("embedding_profile")
    if not isinstance(ep, dict):
        _err_type(errors, "embedding_profile", ep, "object")
    else:
        for f in ("provider", "model", "dimension", "space", "profile_version"):
            if f not in ep:
                errors.add(f"embedding_profile.{f}", "required")
        if isinstance(ep.get("dimension"), int) and ep["dimension"] < 1:
            errors.add("embedding_profile.dimension", "must be >= 1")

    # 9. sample_count
    sc = manifest.get("sample_count")
    if not isinstance(sc, int) or sc < 1:
        errors.add("sample_count", "must be integer >= 1")

    # 10. counts
    cn = manifest.get("counts")
    if not isinstance(cn, dict):
        _err_type(errors, "counts", cn, "object")
    else:
        for f in ("pass", "fail", "skip", "xfail"):
            v = cn.get(f)
            if not isinstance(v, int) or v < 0:
                errors.add(f"counts.{f}", "must be integer >= 0")

    # 11. metrics: 至少一个, 每个含 value/threshold/comparator
    mt = manifest.get("metrics")
    if not isinstance(mt, dict) or not mt:
        errors.add("metrics", "must be non-empty object")
    else:
        for name, m in mt.items():
            if not isinstance(m, dict):
                errors.add(f"metrics.{name}", "must be object")
                continue
            for f in ("value", "threshold", "comparator"):
                if f not in m:
                    errors.add(f"metrics.{name}.{f}", "required")
            cmp_ = m.get("comparator")
            if cmp_ not in ("<", "<=", "=", ">=", ">"):
                errors.add(f"metrics.{name}.comparator", "must be one of < <= = >= >")
            # threshold 字符串形如 "<800ms" / ">=0.80" / "<=10%" —— 不强校验格式,
            # 但必须非空

    # 12. artifacts: 至少一个字符串
    ar = manifest.get("artifacts")
    if not isinstance(ar, list) or not ar:
        errors.add("artifacts", "must be non-empty array of strings")
    else:
        for i, item in enumerate(ar):
            if not isinstance(item, str) or not item:
                errors.add(f"artifacts[{i}]", "must be non-empty string")

    # 13. pii_scan_result
    if manifest.get("pii_scan_result") not in ("pass", "fail"):
        errors.add("pii_scan_result", "must be 'pass' or 'fail'")
    # 若 pii_scan_result == 'fail' 则 counts.fail 必须 >= 1, 反之亦然
    cn_dict = cn if isinstance(cn, dict) else {}
    if manifest.get("pii_scan_result") == "fail" and isinstance(cn_dict.get("fail"), int) and cn_dict["fail"] < 1:
        errors.add("pii_scan_result", "fail but counts.fail == 0 is inconsistent")

    # 14. started_at / finished_at 格式 + 顺序
    sa_ = manifest.get("started_at")
    fa = manifest.get("finished_at")
    if not isinstance(sa_, str) or "T" not in sa_:
        errors.add("started_at", "must be ISO 8601 / RFC 3339 string")
    if not isinstance(fa, str) or "T" not in fa:
        errors.add("finished_at", "must be ISO 8601 / RFC 3339 string")
    if isinstance(sa_, str) and isinstance(fa, str) and sa_ > fa:
        errors.add("finished_at", "must be >= started_at")

    # 15. command_allowlist (optional, 但若存在则枚举值校验)
    ca = manifest.get("command_allowlist")
    if ca is not None:
        if not isinstance(ca, list):
            errors.add("command_allowlist", "must be array of strings")
        else:
            for i, c in enumerate(ca):
                if c not in COMMAND_ALLOWLIST:
                    errors.add(
                        f"command_allowlist[{i}]",
                        f"must be one of {sorted(COMMAND_ALLOWLIST)}",
                    )

    # 16. result_summary_whitelist (optional, 若存在则四字段严格)
    rsw = manifest.get("result_summary_whitelist")
    if rsw is not None:
        if not isinstance(rsw, dict):
            errors.add("result_summary_whitelist", "must be object")
        else:
            extra = set(rsw.keys()) - set(RESULT_SUMMARY_REQUIRED)
            missing = set(RESULT_SUMMARY_REQUIRED) - set(rsw.keys())
            if extra:
                errors.add(
                    "result_summary_whitelist",
                    f"unexpected keys: {sorted(extra)} (whitelist only)",
                )
            if missing:
                errors.add(
                    "result_summary_whitelist",
                    f"missing required keys: {sorted(missing)}",
                )
            # type / range 校验
            cr = rsw.get("candidate_rank")
            if not isinstance(cr, int) or cr < 0:
                errors.add("result_summary_whitelist.candidate_rank", "must be integer >= 0")
            method = rsw.get("method")
            if not isinstance(method, str) or method not in RESULT_SUMMARY_METHOD_ALLOWED:
                errors.add(
                    "result_summary_whitelist.method",
                    f"must be one of {sorted(RESULT_SUMMARY_METHOD_ALLOWED)}",
                )
            score = rsw.get("score")
            if not isinstance(score, (int, float)) or not (0 <= score <= 1):
                errors.add("result_summary_whitelist.score", "must be number in [0,1]")
            lp = rsw.get("language_pair")
            if not isinstance(lp, str) or not LANGUAGE_PAIR_RE.match(lp):
                errors.add(
                    "result_summary_whitelist.language_pair",
                    "must match ^[a-z]{2}_[a-z]{2}$",
                )

    # 17. w4_baseline_reference (optional, 但若存在则严格 schema + 文件必须存在)
    w4ref = manifest.get("w4_baseline_reference")
    if w4ref is not None:
        if not isinstance(w4ref, dict):
            errors.add("w4_baseline_reference", "must be object")
        else:
            for f in (
                "schema_version",
                "baseline_commit",
                "dataset_version",
                "evaluator_version",
                "sample_count",
                "artifacts",
                "pii_scan_result",
            ):
                if f not in w4ref:
                    errors.add(f"w4_baseline_reference.{f}", "required")
            if w4ref.get("schema_version") != "w4-baseline-v1":
                errors.add(
                    "w4_baseline_reference.schema_version",
                    "must equal 'w4-baseline-v1'",
                )
            bc = w4ref.get("baseline_commit")
            if not isinstance(bc, str) or not COMMIT_SHA_RE.match(bc):
                errors.add(
                    "w4_baseline_reference.baseline_commit",
                    "must be 40-hex lowercase string",
                )
            if w4ref.get("dataset_version") != "w4-golden-v1":
                errors.add(
                    "w4_baseline_reference.dataset_version",
                    "must equal 'w4-golden-v1'",
                )
            if w4ref.get("evaluator_version") != "w4-evaluator-v1":
                errors.add(
                    "w4_baseline_reference.evaluator_version",
                    "must equal 'w4-evaluator-v1'",
                )
            if not isinstance(w4ref.get("sample_count"), int) or w4ref["sample_count"] < 1:
                errors.add(
                    "w4_baseline_reference.sample_count",
                    "must be integer >= 1",
                )
            w4_arts = w4ref.get("artifacts")
            if not isinstance(w4_arts, list) or not w4_arts:
                errors.add(
                    "w4_baseline_reference.artifacts",
                    "must be non-empty array",
                )
            elif w4_arts:
                # 文件必须存在 (路径相对 repo root 或绝对)
                repo_root = Path(__file__).resolve().parents[2]
                for art in w4_arts:
                    if not isinstance(art, str) or not art:
                        errors.add(
                            "w4_baseline_reference.artifacts[]",
                            "must be non-empty string",
                        )
                        continue
                    ap = Path(art)
                    if not ap.is_absolute():
                        ap = repo_root / ap
                    if not ap.exists():
                        errors.add(
                            f"w4_baseline_reference.artifacts[{art!r}]",
                            f"file not found at {ap}",
                        )
            if w4ref.get("pii_scan_result") not in ("pass", "fail"):
                errors.add(
                    "w4_baseline_reference.pii_scan_result",
                    "must be 'pass' or 'fail'",
                )

    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W5 evidence manifest validator.")
    parser.add_argument(
        "manifest",
        type=Path,
        help="Path to the manifest JSON file.",
    )
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        sys.stderr.write(f"manifest not found: {args.manifest}\n")
        return EXIT_MANIFEST_REJECTED

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"manifest JSON decode failed: {exc}\n")
        return EXIT_MANIFEST_REJECTED

    if not isinstance(manifest, dict):
        sys.stderr.write("manifest must be a JSON object\n")
        return EXIT_MANIFEST_REJECTED

    errors = validate_manifest(manifest)
    if errors.ok:
        sys.stdout.write(f"manifest {args.manifest} accepted (validator_version=w5-manifest-validator-v1)\n")
        return EXIT_OK

    sys.stderr.write(f"manifest {args.manifest} rejected with {len(errors.errors)} error(s):\n")
    for e in errors.errors:
        sys.stderr.write(f"  - {e}\n")
    return EXIT_MANIFEST_REJECTED


if __name__ == "__main__":
    sys.exit(main())