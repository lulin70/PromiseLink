"""Golden baseline runner (W2, FR-5).

Two modes (PRD FR-3/FR-5, decision D4):
  Mock mode (default): zero LLM cost — validates every case file against
  GoldenCase schema, synthetic-name/PII rules, and contract-document sync.
  Runs on every push (CI push layer).
  LLM mode (GOLDEN_RUN_LLM=1): real extraction via LLMClient, field-level
  diff vs golden labels. Opt-in only (cost control); informational — does
  not block merges (baseline comparison judged by humans, TEST PLAN §3.3).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

from promiselink.core.contract import compute_contract_version
from tests.golden.case_schema import GoldenCase
from tests.golden.synthetic_names import (
    SYNTHETIC_COMPANY_NAMES,
    SYNTHETIC_PERSON_NAMES,
)

GOLDEN_DIR = Path(__file__).parent
CASE_FILES = {
    "must_extract": GOLDEN_DIR / "cases" / "must_extract.json",
    "must_not": GOLDEN_DIR / "cases" / "must_not.json",
    "ambiguous": GOLDEN_DIR / "cases" / "ambiguous.json",
}
CONTRACT_DOC = Path("docs/spec/PARSING_SEMANTIC_CONTRACT.md")

# 手机号/邮箱格式（PII 红线扫描；0700/0000 段伪造号码也禁止出现）
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _load_cases() -> list[dict]:
    cases: list[dict] = []
    for layer, path in CASE_FILES.items():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw["cases"]:
            assert item["layer"] == layer, f"{item['id']}: layer 与文件不符"
            cases.append(item)
    return cases


ALL_CASES = _load_cases()
CASE_IDS = [c["id"] for c in ALL_CASES]


class TestGoldenCaseIntegrity:
    """Mock mode part 1: case file validity (runs on every push)."""

    def test_all_cases_parse_and_layer_count(self):
        by_layer = {"must_extract": 0, "must_not": 0, "ambiguous": 0}
        for item in ALL_CASES:
            case = GoldenCase.model_validate(item)  # raises on invalid
            by_layer[case.layer] += 1
        assert by_layer["must_extract"] >= 15
        assert by_layer["must_not"] >= 5
        assert by_layer["ambiguous"] >= 10
        assert len({c["id"] for c in ALL_CASES}) == len(ALL_CASES), "用例 id 重复"

    def test_person_names_from_synthetic_pool(self):
        """PII 红线：期望人名必须来自虚构名池。"""
        pool = set(SYNTHETIC_PERSON_NAMES)
        for item in ALL_CASES:
            for name in item["expected"].get("person_names", []):
                assert name in pool, f"{item['id']}: 人名「{name}」不在虚构名池"

    def test_no_pii_patterns_in_inputs(self):
        """PII 红线：输入文本不得含手机号/邮箱格式。"""
        for item in ALL_CASES:
            text = item["input_text"]
            assert not _PHONE_RE.search(text), f"{item['id']}: 疑似手机号"
            assert not _EMAIL_RE.search(text), f"{item['id']}: 疑似邮箱"

    def test_layer_assertions_consistent(self):
        for item in ALL_CASES:
            exp = item["expected"]
            if item["layer"] == "must_extract":
                assert exp["min_persons"] >= 1, f"{item['id']}: must_extract 须要求人"
                assert not exp.get("expect_confirmation"), f"{item['id']}: 层级断言矛盾"
            elif item["layer"] == "must_not":
                assert exp["min_persons"] == 0 and exp.get("max_persons") == 0, item["id"]
            else:  # ambiguous
                assert exp.get("expect_confirmation") is True, (
                    f"{item['id']}: ambiguous 层必须断言进入确认流程"
                )

    def test_company_names_from_synthetic_pool(self):
        """期望人名/公司归属校验收敛于结构化字段（自由文本启发式不可靠，
        按测试哲学只断言可明确断言之物）；文本层 PII 由格式扫描兜底。"""
        person_pool = set(SYNTHETIC_PERSON_NAMES)
        company_pool = set(SYNTHETIC_COMPANY_NAMES)
        for item in ALL_CASES:
            for name in item["expected"].get("person_names", []):
                assert name in person_pool, f"{item['id']}: 人名「{name}」不在虚构池"
            # expected 不得引用真实公司后缀结构（防止标注期混入真实公司）
            blob = json.dumps(item["expected"], ensure_ascii=False)
            for m in re.findall(
                r"[\u4e00-\u9fff]{2,4}(?:科技|资本|制造|物流|数据|新材|智能|传媒|生物|能源)",
                blob,
            ):
                assert any(m.endswith(c) for c in company_pool), (
                    f"{item['id']}: expected 中公司「{m}」不在虚构池"
                )


class TestContractDocumentSync:
    """Mock mode part 2: contract document matches live code (CI push layer)."""

    def test_contract_doc_version_matches_code(self):
        doc = CONTRACT_DOC.read_text(encoding="utf-8")
        version = compute_contract_version()
        assert f"v={version}" in doc, (
            f"契约文档哈希过期：代码={version}，请运行 "
            "python scripts/generate_semantic_contract.py --write"
        )

    def test_human_section_preserved(self):
        doc = CONTRACT_DOC.read_text(encoding="utf-8")
        assert "### 6.1 关键字段的业务含义与必填性理由" in doc, "人工语义说明段丢失"


@pytest.mark.skipif(
    os.environ.get("GOLDEN_RUN_LLM") != "1",
    reason="LLM 模式需显式 GOLDEN_RUN_LLM=1（成本控制，PRD FR-5）",
)
class TestGoldenLLMBaseline:
    """LLM mode: real extraction vs golden labels (opt-in, informational)."""

    @pytest.mark.parametrize("case_id", CASE_IDS)
    def test_extraction_vs_golden(self, case_id: str):
        from promiselink.prompts.entity_extraction import (
            _CAPABILITY_STR,
            _CONCERN_STR,
            TEMPLATE_2_CONVERSATION_EXTRACTION,
        )
        from promiselink.services.llm_client import LLMClient

        item = next(c for c in ALL_CASES if c["id"] == case_id)
        prompt = TEMPLATE_2_CONVERSATION_EXTRACTION.format(
            language="zh-CN",
            transcript=item["input_text"],
            concern_terms=_CONCERN_STR,
            capability_terms=_CAPABILITY_STR,
        )
        client = LLMClient()
        response = asyncio.run(
            client.call_json(prompt=prompt, temperature=0.2)
        )

        names = [p.get("name") for p in response.get("persons", [])]
        requires_confirmation = bool(response.get("requires_confirmation"))

        if item["layer"] == "must_not":
            assert not names, f"{case_id}: 闲聊不应提取人脉，实际提取 {names}"
        elif item["layer"] == "must_extract":
            expected_names = set(item["expected"]["person_names"])
            missing = expected_names - set(names or [])
            assert len(names or []) >= item["expected"]["min_persons"], (
                f"{case_id}: 人脉数不足，期望≥{item['expected']['min_persons']}，实际 {names}"
            )
            # 允许 LLM 多提取，但不得遗漏标注的关键人名（字段级裁决留给报告）
            assert not missing, f"{case_id}: 遗漏标注人名 {missing}"
        else:  # ambiguous
            assert requires_confirmation, (
                f"{case_id}: 歧义用例必须 requires_confirmation=True（纠偏入口）"
            )
