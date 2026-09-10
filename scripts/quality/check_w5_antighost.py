"""W5 anti-ghost runner — CLI skeleton (NOT IMPLEMENTED).

This file establishes the CLI surface, exit codes, and argument contract
required by the W5 anti-ghost discipline (Test Plan §16.1). The runner
MUST exit non-zero and emit a manifest-shaped ``pending`` placeholder
when called before Implementation is authorized. Once Implementation is
authorized, the placeholder body is replaced with the real
``_call_counter`` sweep across the candidate-token signer/verifier,
multilingual resolver, embedding-space isolation, and operation-audit
modules.

Contract frozen in this skeleton (do NOT change without sign-off):
  exit codes:
    0   all required W5 modules invoked and call counters > 0
    2   pending implementation (CLI invoked before sign-off)
    3   missing manifest artifact path or counter table
    4   PII / secret scan failure
  CLI:
    check_w5_antighost.py [--manifest PATH] [--strict-markers]
                           [--ci]
  Output:
    docs/evidence/w5_antighost/<timestamp>.json manifest
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PENDING_EXIT_CODE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_w5_antighost",
        description=(
            "W5 anti-ghost runner. Skeleton only; real implementation "
            "lands after Implementation Authorization."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/evidence/w5_antighost/manifest.json"),
        help="Output manifest path (must satisfy W5 evidence schema v1).",
    )
    parser.add_argument(
        "--strict-markers",
        action="store_true",
        help="Fail the run if any W5 marker is unused in the run set.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: stricter thresholds and non-zero exit on any warning.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sys.stderr.write(
        "[check_w5_antighost] pending: W5 implementation not yet authorized; "
        "see docs/design/W5_IMPLEMENTATION_READINESS_CHECKLIST_v1.md §6.\n"
    )
    sys.stderr.write(
        f"[check_w5_antighost] would write manifest to {args.manifest}\n"
    )
    return PENDING_EXIT_CODE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())