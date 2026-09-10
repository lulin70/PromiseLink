"""W5 activation counters — Anti-ghost honest ground truth.

DevSquad Anti-Ghost Principle (V4.5.16, ref: SUB_SKILLS.md):
    "Every module shipped in DevSquad must prove it is wired into the real
     execution path — not just present on disk."

For PromiseLink W5, the four critical control points that MUST show evidence of
real invocation (not just import) are:

  1. Candidate-token signer        (core.auth.issue_candidate_token)
  2. Candidate-token verifier      (core.auth.verify_candidate_token)
  3. Multilingual resolver hook    (services.entity_resolution / synonym_dict)
  4. Embedding-space isolation     (services.embedding_provider._cache_key)
  5. Operation/audit state machine (services.w5_operation_service.claim/complete)

This module exposes module-level counter dicts that the production entry points
increment on every real call. The Anti-ghost runner (scripts/quality/
check_w5_antighost.py) reads these counters at run time and asserts
`counter > 0` for each control point.

Design contract (DO NOT change without sign-off):
  - Counters are process-local (not persisted). A persisted "ever-activated"
    claim would itself be a ghost source. Fresh process + exercised path = real.
  - Reset is exposed only via the dedicated `reset_counters()` helper, used by
    the runner to start from a clean baseline before the deterministic
    synthetic probe.
  - `summarize()` returns a JSON-serializable dict safe to embed in the W5
    evidence manifest (see docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json).
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Process-local counter storage. Use a lock so multi-threaded ASGI workers
# (sync test fixtures) cannot lose increments during a probe sweep.
_lock = threading.Lock()

# Each counter is a list so we can carry the timestamp of the last invocation
# alongside the total. That timestamp is what the runner asserts against its
# own run_started_at (i.e., "this counter moved during THIS run").
_counters: dict[str, list[int]] = {
    "issue_candidate_token": [0, 0],
    "verify_candidate_token": [0, 0],
    "multilingual_resolver": [0, 0],
    "embedding_space_isolation": [0, 0],
    "operation_state_machine": [0, 0],
}
_last_invocation_ts: dict[str, float] = {k: 0.0 for k in _counters}

# Logical module path that emitted the increment. Used for diagnostics only;
# the runner only consumes the counters themselves.
_source_module: dict[str, str] = {
    "issue_candidate_token": "promiselink.core.auth",
    "verify_candidate_token": "promiselink.core.auth",
    "multilingual_resolver": "promiselink.services.entity_resolution",
    "embedding_space_isolation": "promiselink.services.embedding_provider",
    "operation_state_machine": "promiselink.services.w5_operation_service",
}


def record(control_point: str) -> None:
    """Increment the counter for a W5 control point. No-op for unknown keys.

    Production call sites wrap this with a one-line guarded increment:
        try:
            from promiselink.core.activation import record as _record_w5
            _record_w5("issue_candidate_token")
        except Exception:  # never let observability break the production path
            pass
    """
    if control_point not in _counters:
        return
    with _lock:
        total, _ = _counters[control_point]
        _counters[control_point] = [total + 1, int(time.time())]
        _last_invocation_ts[control_point] = time.time()


def reset_counters() -> None:
    """Zero out every counter. Used by the runner to start clean."""
    with _lock:
        for key in _counters:
            _counters[key] = [0, 0]
            _last_invocation_ts[key] = 0.0


def snapshot() -> dict[str, dict[str, Any]]:
    """Return a JSON-safe dict of current counter values + last invocation ts."""
    with _lock:
        out: dict[str, dict[str, Any]] = {}
        for key, (total, _last) in _counters.items():
            out[key] = {
                "count": total,
                "last_invocation_ts": _last_invocation_ts[key],
                "source_module": _source_module.get(key, ""),
            }
        return out


def required_control_points() -> tuple[str, ...]:
    """The five control points the runner asserts > 0 on."""
    return tuple(_counters.keys())


__all__ = [
    "record",
    "reset_counters",
    "snapshot",
    "required_control_points",
]
