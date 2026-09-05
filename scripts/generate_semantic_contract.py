#!/usr/bin/env python3
"""Generate the parsing semantic contract document (W1, FR-1).

Single source of truth = code (five sources, see promiselink.core.contract).
This script renders them into docs/spec/PARSING_SEMANTIC_CONTRACT.md.

Human-maintained "semantic notes" live inside <!-- human-section:... -->
markers and are preserved across regeneration (TD-044 lesson: generated
sections are never hand-edited; hand sections are never generated).

Usage:
  python scripts/generate_semantic_contract.py            # print to stdout
  python scripts/generate_semantic_contract.py --write    # update doc in place
  python scripts/generate_semantic_contract.py --check    # CI: exit 1 on drift
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from promiselink.core.contract import (  # noqa: E402
    CAPABILITY_TERMS,
    CONCERN_TERMS,
    collect_contract_sources,
    compute_contract_version,
)

DOC_PATH = Path("docs/spec/PARSING_SEMANTIC_CONTRACT.md")
GEN_OPEN = "<!-- generated:do-not-edit:v={version} -->"
GEN_CLOSE = "<!-- /generated -->"
HUMAN_OPEN = "<!-- human-section:semantic-notes -->"
HUMAN_CLOSE = "<!-- /human-section -->"


def _extract_human_section(doc_text: str) -> str:
    """Preserve the human-maintained section across regeneration."""
    if HUMAN_OPEN not in doc_text or HUMAN_CLOSE not in doc_text:
        return ""
    start = doc_text.index(HUMAN_OPEN) + len(HUMAN_OPEN)
    end = doc_text.index(HUMAN_CLOSE)
    return doc_text[start:end].strip("\n")


def _render_concepts(sources: dict) -> list[str]:
    lines = []
    lines.append("### Event（互动事件）")
    lines.append("一次录入的原始互动记录（会议/通话/名片/手动/跟进/语音查询等）。")
    lines.append("")
    lines.append("### Entity（人脉）")
    lines.append("从事件中抽取的真实人物；附 `properties` JSONB（结构见 §2.1）。")
    lines.append("")
    lines.append("### Todo（待办，含 Promise 逻辑视图）")
    lines.append(
        "从事件派生的行动项；Promise（承诺）复用 todos 表，"
        "以 todo_type 区分（promise/followup 等），双向分析见 Step05。"
    )
    lines.append("")
    lines.append("### ExtractionResult（解析输出契约）")
    for f in sources["extraction_result_fields"]:
        lines.append(f"- `{f['field']}`: {f['type']}")
    return lines


def _render_attributes(sources: dict) -> list[str]:
    lines = ["### 2.1 Entity.properties 结构（EntityProperties schema）", ""]
    props = sources["entity_properties_schema"]
    defs = props.get("$defs", props.get("definitions", {}))

    def _model_props(model_name: str) -> None:
        model = defs.get(model_name, {})
        lines.append(f"**{model_name}**")
        lines.append("")
        for pname, pdef in (model.get("properties") or {}).items():
            ptype = pdef.get("type", pdef.get("$ref", "any"))
            if isinstance(ptype, list):
                ptype = " | ".join(ptype)
            lines.append(f"- `{pname}`: {ptype}")
        lines.append("")

    for model_name in ("BasicInfo", "ConcernItem", "CapabilityItem", "EntityProperties"):
        _model_props(model_name)

    lines.append("### 2.2 ORM 存储字段")
    lines.append("")
    for table, cols in sources["orm_columns"].items():
        lines.append(f"**{table}**（{len(cols)} 列）")
        lines.append("")
        lines.append("| 列 | 类型 | 可空 |")
        lines.append("|---|---|---|")
        for c in cols:
            lines.append(f"| `{c['column']}` | {c['type']} | {'是' if c['nullable'] else '否'} |")
        lines.append("")
    return lines


def _render_relations(sources: dict) -> list[str]:
    # 事实来源：ORM 外键/关联 + 领域语义（Step05 双向承诺、Step11 关联发现）
    return [
        "- `Entity` ↔ `Event`：多对多参与（事件中出现的人脉；关联发现 Step10/Step11 维护）",
        "- `Todo` → `Event`：待办源于事件（Step04 生成）",
        "- `Todo`(promise) ↔ 双方 Entity：承诺双向分析（Step05，我对他人/他人对我）",
        "- `Entity` ↔ `Entity`：关联网络（AssociationDiscoveryEngine，共现/频率规则）",
        "- `RelationshipBrief` → `Entity`：关系简报随互动持续更新（Step12）",
    ]


def _render_constraints(sources: dict) -> list[str]:
    return [
        "1. 虚拟角色不提取：PM/架构师等职能词、第一人称「我」均不是人脉（prompt 硬规则）",
        "2. 禁止对他人资源做确定性判断；推测内容必须标注（来源：原文引用）",
        "3. 禁止建议索取资源",
        "4. `Entity.properties` 写库前必须过 `EntityProperties` 校验（失败降级存储原文并告警）",
        "5. concern/capability 的 category 受控词表约束（§5.1/§5.2），detail 为自由文本",
        "6. 信息不足字段设为 null，禁止编造",
        "7. 歧义（多候选人脉/时间）必须进入人工纠偏流程（requires_confirmation）",
    ]


def _render_enums(sources: dict) -> list[str]:
    lines = ["### 5.1 concern 受控词表", ""]
    lines.append("、".join(CONCERN_TERMS))
    lines.append("")
    lines.append("### 5.2 capability 受控词表")
    lines.append("")
    lines.append("、".join(CAPABILITY_TERMS))
    lines.append("")
    lines.append("### 5.3 InputScope 输入范围（8 类）")
    lines.append("")
    for v in sources["input_scope_enum"]:
        lines.append(f"- `{v}`")
    lines.append("")
    lines.append("### 5.4 confidence_level 输出置信度")
    lines.append("")
    lines.append("- `confirmed` | `inferred` | `speculated`")
    lines.append("")
    return lines


def render_document() -> str:
    sources = collect_contract_sources()
    version = compute_contract_version()

    parts: list[str] = []
    parts.append("# PromiseLink 解析语义契约")
    parts.append("")
    parts.append(f"> **契约版本**: `{version}`（由代码五源内容哈希自动计算，勿手改）")
    parts.append("> **生成**: `python scripts/generate_semantic_contract.py --write`")
    parts.append("> **父文档**: [PRD_解析语义契约_v1.md](PRD_解析语义契约_v1.md)")
    parts.append("")

    gen: list[str] = []
    gen.append("## 1. 概念（Class）")
    gen.append("")
    gen.extend(_render_concepts(sources))
    gen.append("## 2. 属性")
    gen.append("")
    gen.extend(_render_attributes(sources))
    gen.append("## 3. 关系")
    gen.append("")
    gen.extend(_render_relations(sources))
    gen.append("")
    gen.append("## 4. 约束")
    gen.append("")
    gen.extend(_render_constraints(sources))
    gen.append("")
    gen.append("## 5. 枚举与受控词表")
    gen.append("")
    gen.extend(_render_enums(sources))

    parts.append(GEN_OPEN.format(version=version))
    parts.extend(gen)
    parts.append(GEN_CLOSE)
    parts.append("")

    human = _extract_human_section(DOC_PATH.read_text(encoding="utf-8")) if DOC_PATH.exists() else ""
    parts.append(HUMAN_OPEN)
    if human:
        parts.append(human)
    else:
        parts.append("## 6. 语义说明（人工维护）")
        parts.append("")
        parts.append("<!-- 首次生成后在此补充：字段业务含义、必填性理由、歧义处理策略 -->")
    parts.append(HUMAN_CLOSE)
    parts.append("")

    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update doc in place")
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 if doc drifts from code"
    )
    args = parser.parse_args()

    rendered = render_document()

    if args.check:
        if not DOC_PATH.exists():
            print(f"FAIL: {DOC_PATH} 不存在（先运行 --write 生成）", file=sys.stderr)
            return 1
        current = DOC_PATH.read_text(encoding="utf-8")
        if current != rendered:
            import difflib

            diff = difflib.unified_diff(
                current.splitlines(),
                rendered.splitlines(),
                fromfile="on-disk",
                tofile="generated",
                lineterm="",
            )
            print("\n".join(diff), file=sys.stderr)
            print("FAIL: 契约文档与代码不同步（schema/词表/枚举变更后未重新生成）", file=sys.stderr)
            return 1
        print("OK: contract document in sync")
        return 0

    if args.write:
        DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(rendered, encoding="utf-8")
        print(f"written: {DOC_PATH}")
        return 0

    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
