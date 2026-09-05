"""Parsing semantic contract — single source of truth for the contract version.

W1 of the Ontology semantic-contract plan (docs/spec/PRD_解析语义契约_v1.md).

The contract version is a content hash over five code facts (五源):
  S1 entity properties schema   (schemas/entity_properties.py)
  S2 ORM models                  (models/event.py, entity.py, todo.py)
  S3 extraction controlled vocab (CONCERN_TERMS / CAPABILITY_TERMS here)
  S4 input scope enum            (services/input_scope_classifier.py)
  S5 extraction output contract  (services/entity_extractor.ExtractionResult)

No separate version file exists — the hash is computed from live code at
runtime (<10ms), so the contract cannot drift from the code (TD-044 lesson:
hand-maintained duplicate lists always drift).

Shared by:
  - scripts/generate_semantic_contract.py (document generation + CI diff)
  - entity_extractor logging (contract_version field)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

# ── S3: Controlled vocabularies (受控词表) ──────────────────────────────
# Injected into prompt templates via format() — the prompt strings hold
# {concern_terms}/{capability_terms} placeholders, so vocabulary lives in
# exactly one place (single source of truth).

CONCERN_TERMS: list[str] = [
    "融资", "招聘", "销售", "技术选型", "合规", "市场拓展",
    "成本控制", "供应链", "数字化转型", "人才保留",
]

CAPABILITY_TERMS: list[str] = [
    "投资决策", "技术架构", "产品设计", "项目管理", "渠道资源",
    "行业人脉", "政策解读", "数据分析", "品牌营销", "团队管理",
]


def _canonical(payload: Any) -> str:
    """Deterministic JSON serialization for hashing."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _collect_entity_properties() -> Any:
    from promiselink.schemas.entity_properties import EntityProperties

    return EntityProperties.model_json_schema()


def _collect_orm_columns() -> dict[str, list[dict[str, Any]]]:
    from promiselink.models.entity import Entity
    from promiselink.models.event import Event
    from promiselink.models.todo import Todo

    out: dict[str, list[dict[str, Any]]] = {}
    for name, model in (("Event", Event), ("Entity", Entity), ("Todo", Todo)):
        out[name] = [
            {"column": col.name, "type": str(col.type), "nullable": col.nullable}
            for col in model.__table__.columns
        ]
    return out


def _collect_vocab() -> dict[str, list[str]]:
    return {"concern": CONCERN_TERMS, "capability": CAPABILITY_TERMS}


def _collect_input_scope() -> list[str]:
    from promiselink.services.input_scope_classifier import InputScope

    return [member.value for member in InputScope]


def _collect_extraction_result() -> list[dict[str, Any]]:
    from promiselink.services.entity_extractor import ExtractionResult

    return [
        {"field": f.name, "type": str(f.type)}
        for f in dataclasses.fields(ExtractionResult)
    ]


def collect_contract_sources() -> dict[str, Any]:
    """Collect the five contract sources (S1-S5) as canonical JSON-able data.

    Used by compute_contract_version() and by the document generator —
    one implementation, never two.
    """
    return {
        "entity_properties_schema": _collect_entity_properties(),
        "orm_columns": _collect_orm_columns(),
        "controlled_vocab": _collect_vocab(),
        "input_scope_enum": _collect_input_scope(),
        "extraction_result_fields": _collect_extraction_result(),
    }


def compute_contract_version() -> str:
    """Content hash (sha256, first 12 hex chars) over the five sources."""
    payload = _canonical(collect_contract_sources())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
