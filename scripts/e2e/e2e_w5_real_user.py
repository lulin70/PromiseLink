"""W5 real-user API/UI E2E — CLI skeleton (NOT IMPLEMENTED).

Skeleton only. Establishes the CLI surface and exit-code contract required
by Test Plan §13 (E-W5-01..E-W5-08) and §16.1. Once Implementation is
authorized, the placeholder body is replaced with the real flow:
synthetic data generation → live API calls → UI smoke via Playwright
(if already wired in W3/W4) → manifest emission → Anti-ghost handoff.

Contract frozen in this skeleton (do NOT change without sign-off):
  exit codes:
    0   real-user black-box run completed; manifest valid
    2   pending implementation
    3   API server not reachable
    4   manifest validator rejected
    5   PII / secret scan failure
  CLI:
    e2e_w5_real_user.py --api-base URL
                        [--ui-base URL]
                        [--manifest PATH]
                        [--ci]
"""

from __future__ import annotations

import argparse
import sys

PENDING_EXIT_CODE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2e_w5_real_user",
        description=(
            "W5 real-user API/UI end-to-end. Skeleton only; real flow "
            "lands after Implementation Authorization."
        ),
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="Base URL of the running PromiseLink API server.",
    )
    parser.add_argument(
        "--ui-base",
        default=None,
        help="Base URL of the running frontend (optional, Playwright-driven).",
    )
    parser.add_argument(
        "--manifest",
        default="docs/evidence/w5_e2e/manifest.json",
        help="Output manifest path (must satisfy W5 evidence schema v1).",
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
        "[e2e_w5_real_user] pending: W5 implementation not yet authorized; "
        "see docs/design/W5_IMPLEMENTATION_READINESS_CHECKLIST_v1.md §6.\n"
    )
    sys.stderr.write(
        f"[e2e_w5_real_user] would target api={args.api_base} "
        f"ui={args.ui_base} manifest={args.manifest}\n"
    )
    return PENDING_EXIT_CODE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())