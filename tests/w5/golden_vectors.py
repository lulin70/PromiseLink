"""W5 cross-language golden vectors (entity + todo).

最小 8 组 entity + 2 组 todo, 覆盖 en↔zh 与 ja↔zh 双向, person/company 各 ≥ 1,
按 PRD §6 / Tech Design §5 / Test Plan §5.4 已固化.

每行 JSON 包含:
- id:        golden sample id (跨语言唯一)
- language_pair: zh_en / en_zh / zh_ja / ja_zh 之一
- direction: source_to_target ('en_to_zh' / 'zh_to_en' / ...)
- entity_type: person / company / todo
- source: { name, company?, title?, due_date? }  -- 原始输入语言
- expected_candidates: 期望候选列表, 字段含 rank / canonical_name / score / method

Negative samples: 至少 6 条, 分 6 个语言方向, 每条至少 1 条 negative
(即 expected_candidates 为空数组, 不可触发任何候选).
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"

W5_GOLDEN_V1 = {
    "schema_version": "w5-golden-v1",
    "evaluator_version": "w5-evaluator-v1",
    "created_at": "2026-09-10T00:00:00Z",
    "language_pairs_supported": ["zh_en", "en_zh", "zh_ja", "ja_zh"],
    "samples": [
        # ── Positive samples (跨语言, person) ──
        {
            "id": "E-01",
            "language_pair": "zh_en",
            "direction": "zh_to_en",
            "entity_type": "person",
            "source": {"name": "林晚秋"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "Lin Wanqiu", "score_min": 0.85,
                 "method": "cross_language_match"}
            ],
        },
        {
            "id": "E-02",
            "language_pair": "en_zh",
            "direction": "en_to_zh",
            "entity_type": "person",
            "source": {"name": "Lin Wanqiu", "company": "Acme Corp"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "林晚秋", "score_min": 0.80,
                 "method": "cross_language_match"}
            ],
        },
        {
            "id": "E-03",
            "language_pair": "ja_zh",
            "direction": "ja_to_zh",
            "entity_type": "person",
            "source": {"name": "林晩秋"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "林晚秋", "score_min": 0.80,
                 "method": "cross_language_match"}
            ],
        },
        {
            "id": "E-04",
            "language_pair": "zh_ja",
            "direction": "zh_to_ja",
            "entity_type": "person",
            "source": {"name": "林晚秋"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "林晩秋", "score_min": 0.80,
                 "method": "cross_language_match"}
            ],
        },
        # ── Positive samples (跨语言, company) ──
        {
            "id": "E-05",
            "language_pair": "en_zh",
            "direction": "en_to_zh",
            "entity_type": "company",
            "source": {"name": "Acme Corporation", "title": "CEO"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "Acme 公司", "score_min": 0.80,
                 "method": "synonym_match"}
            ],
        },
        {
            "id": "E-06",
            "language_pair": "zh_en",
            "direction": "zh_to_en",
            "entity_type": "company",
            "source": {"name": "Acme 公司"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "Acme Corporation", "score_min": 0.80,
                 "method": "synonym_match"}
            ],
        },
        # ── Negative samples (跨语言不可关联, ≥ 6 条分母) ──
        {
            "id": "E-N01",
            "language_pair": "en_zh",
            "direction": "en_to_zh",
            "entity_type": "person",
            "source": {"name": "John Smith"},
            "expected_candidates": [],
        },
        {
            "id": "E-N02",
            "language_pair": "zh_en",
            "direction": "zh_to_en",
            "entity_type": "person",
            "source": {"name": "王伟"},
            "expected_candidates": [],
        },
        {
            "id": "E-N03",
            "language_pair": "ja_zh",
            "direction": "ja_to_zh",
            "entity_type": "person",
            "source": {"name": "佐藤太郎"},
            "expected_candidates": [],
        },
        {
            "id": "E-N04",
            "language_pair": "zh_ja",
            "direction": "zh_to_ja",
            "entity_type": "person",
            "source": {"name": "张三"},
            "expected_candidates": [],
        },
        {
            "id": "E-N05",
            "language_pair": "en_zh",
            "direction": "en_to_zh",
            "entity_type": "company",
            "source": {"name": "XYZ Industries"},
            "expected_candidates": [],
        },
        {
            "id": "E-N06",
            "language_pair": "ja_zh",
            "direction": "ja_to_zh",
            "entity_type": "company",
            "source": {"name": "ヤマト運輸"},
            "expected_candidates": [],
        },
        # ── Todo positive (中/英 + 有时间) ──
        {
            "id": "T-01",
            "language_pair": "zh_en",
            "direction": "zh_to_en",
            "entity_type": "todo",
            "source": {"title": "下周一前提交季度报告", "due_date": "2026-09-14"},
            "expected_candidates": [
                {"rank": 1, "canonical_name": "Submit quarterly report by Monday",
                 "score_min": 0.75, "method": "cross_language_match"}
            ],
        },
        # ── Todo positive (无时间, 不生成候选) ──
        {
            "id": "T-02",
            "language_pair": "en_zh",
            "direction": "en_to_zh",
            "entity_type": "todo",
            "source": {"title": "Review the contract"},
            "expected_candidates": [],
        },
    ],
}


def write_golden_file(path: Path | None = None) -> Path:
    """Write the golden file to disk; returns the resolved path."""
    target = path or (GOLDEN_DIR / "w5-golden-v1.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    # JSONL format: one JSON object per line (for streaming evaluator)
    with target.open("w", encoding="utf-8") as fp:
        for sample in W5_GOLDEN_V1["samples"]:
            fp.write(json.dumps(sample, ensure_ascii=False) + "\n")
    return target


def count_by_direction() -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in W5_GOLDEN_V1["samples"]:
        d = s["direction"]
        counts[d] = counts.get(d, 0) + 1
    return counts


def negative_count() -> int:
    return sum(1 for s in W5_GOLDEN_V1["samples"] if not s["expected_candidates"])


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: write golden file and print summary."""
    import argparse

    parser = argparse.ArgumentParser(description="W5 golden vector writer.")
    parser.add_argument(
        "--output",
        type=Path,
        default=GOLDEN_DIR / "w5-golden-v1.jsonl",
        help="Output path for the JSONL golden file.",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print summary counts after writing.",
    )
    args = parser.parse_args(argv)

    written = write_golden_file(args.output)
    print(f"wrote {len(W5_GOLDEN_V1['samples'])} samples to {written}")
    if args.print_summary:
        counts = count_by_direction()
        print(f"  by direction: {counts}")
        print(f"  negative samples: {negative_count()}")
        # 校验 negative 分母 ≥ 6 (Test Plan §5.4 收紧)
        if negative_count() < 6:
            print("  WARN: negative sample denominator < 6 (Test Plan §5.4)")
            return 3  # 退出码 3 = 数据不达标 (W5 manifest validator 扩展预留)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())