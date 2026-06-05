"""F-44: Input Scope Classifier — classify event input scope using rule-based + LLM fallback.

Strategy:
  1. Rule-based matching on event_type + source + title keywords (fast, <5ms)
  2. If rule confidence < 0.85, fall back to LLM classification (slower, ~200-500ms)

PRD v4.4 F-44 + Algorithm Design §11
"""

from dataclasses import dataclass
from enum import Enum

from eventlink.core.logging import get_logger
from eventlink.models.event import Event
from eventlink.services.llm_client import LLMClient

logger = get_logger("eventlink.input_scope")


# ── Enum ──


class InputScope(str, Enum):
    """8 input scope categories for events (F-44)."""

    CARD_SCAN = "card_scan"
    MEETING = "meeting"
    CALL = "call"
    MANUAL = "manual"
    FOLLOWUP = "followup"
    VOICE_QUERY = "voice_query"
    REFLECTION = "reflection"
    UNKNOWN = "unknown"


# ── Result ──


@dataclass
class ClassificationResult:
    """Result of input scope classification."""

    scope: InputScope
    confidence: float
    evidence: str
    method: str  # "rule" | "llm"


# ── Classifier ──


class InputScopeClassifier:
    """Classify an event's input scope using rule-based matching with LLM fallback.

    Rule-based classification is fast (<5ms) and preferred to reduce LLM cost
    and latency. When no high-confidence rule matches, falls back to LLM.
    """

    # Confidence threshold for accepting rule-based result without LLM fallback
    RULE_CONFIDENCE_THRESHOLD = 0.85

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def classify(self, event: Event) -> ClassificationResult:
        """Classify an event's input scope.

        Args:
            event: The Event instance to classify.

        Returns:
            ClassificationResult with scope, confidence, evidence, and method.
        """
        logger.info(
            "classify_started",
            event_id=str(event.id),
            event_type=event.event_type,
            source=event.source,
            title=event.title[:50],
        )

        # Step 1: Try rule-based classification
        rule_result = self._rule_classify(event)
        if rule_result is not None and rule_result.confidence >= self.RULE_CONFIDENCE_THRESHOLD:
            logger.info(
                "classify_rule_hit",
                event_id=str(event.id),
                scope=rule_result.scope.value,
                confidence=rule_result.confidence,
                method="rule",
            )
            return rule_result

        # Step 2: Fall back to LLM classification
        llm_result = await self._llm_classify(event)
        logger.info(
            "classify_llm_fallback",
            event_id=str(event.id),
            scope=llm_result.scope.value,
            confidence=llm_result.confidence,
            method="llm",
        )
        return llm_result

    def _rule_classify(self, event: Event) -> ClassificationResult | None:
        """Fast rule-based classification using event_type + source mapping.

        Returns None if no rule matches with sufficient confidence.
        """
        et = event.event_type
        src = event.source.lower() if event.source else ""
        title_lower = event.title.lower() if event.title else ""

        # card_save → card_scan
        if et == "card_save":
            if src in ("wechat_scan", "manual") or src.startswith("wechat"):
                return ClassificationResult(
                    scope=InputScope.CARD_SCAN,
                    confidence=0.95,
                    evidence=f"event_type=card_save, source={event.source}",
                    method="rule",
                )
            # card_save from any other source still likely a scan
            return ClassificationResult(
                scope=InputScope.CARD_SCAN,
                confidence=0.90,
                evidence=f"event_type=card_save (source={event.source})",
                method="rule",
            )

        # meeting → meeting
        if et == "meeting":
            if src in ("calendar", "manual"):
                return ClassificationResult(
                    scope=InputScope.MEETING,
                    confidence=0.95,
                    evidence=f"event_type=meeting, source={event.source}",
                    method="rule",
                )
            return ClassificationResult(
                scope=InputScope.MEETING,
                confidence=0.90,
                evidence=f"event_type=meeting (source={event.source})",
                method="rule",
            )

        # call → call
        if et == "call":
            if src in ("phone", "manual"):
                return ClassificationResult(
                    scope=InputScope.CALL,
                    confidence=0.95,
                    evidence=f"event_type=call, source={event.source}",
                    method="rule",
                )
            return ClassificationResult(
                scope=InputScope.CALL,
                confidence=0.90,
                evidence=f"event_type=call (source={event.source})",
                method="rule",
            )

        # manual → sub-classify by source or title keywords
        if et == "manual":
            # Known sources with high confidence
            if src == "followup_reminder":
                return ClassificationResult(
                    scope=InputScope.FOLLOWUP,
                    confidence=0.90,
                    evidence="source=followup_reminder",
                    method="rule",
                )
            if src == "voice_input":
                return ClassificationResult(
                    scope=InputScope.VOICE_QUERY,
                    confidence=0.90,
                    evidence="source=voice_input",
                    method="rule",
                )
            if src == "reflection_note":
                return ClassificationResult(
                    scope=InputScope.REFLECTION,
                    confidence=0.90,
                    evidence="source=reflection_note",
                    method="rule",
                )

            # Title keyword heuristics for manual events with unknown/other sources
            result = self._keyword_classify(title_lower)
            if result is not None:
                return result

            # No keyword match — low confidence default
            return ClassificationResult(
                scope=InputScope.MANUAL,
                confidence=0.70,
                evidence="manual event with no specific source or keyword match",
                method="rule",
            )

        # Unknown event_type
        return ClassificationResult(
            scope=InputScope.UNKNOWN,
            confidence=0.50,
            evidence=f"unrecognized event_type={et}",
            method="rule",
        )

    @staticmethod
    def _keyword_classify(title_lower: str) -> ClassificationResult | None:
        """Classify by title keywords for manual events with ambiguous source.

        Returns None if no keywords match.
        """
        followup_keywords = ("跟进", "提醒", "remind", "follow-up", "followup", "待办")
        voice_keywords = ("语音", "查询", "搜索", "query", "search", "voice", "speak")
        reflection_keywords = (
            "回顾", "总结", "复盘", "review", "summary", "反思", "周报",
            "月报", "日报", "周结", "月结",
        )
        meeting_keywords = (
            "会议", "面谈", "洽谈", "meeting", "discussion", "讨论会",
        )
        call_keywords = (
            "电话", "通话", "沟通", "call", "phone", "电话会议",
        )

        for kw in followup_keywords:
            if kw in title_lower:
                return ClassificationResult(
                    scope=InputScope.FOLLOWUP,
                    confidence=0.80,
                    evidence=f"title keyword '{kw}' matched as followup",
                    method="rule",
                )

        for kw in voice_keywords:
            if kw in title_lower:
                return ClassificationResult(
                    scope=InputScope.VOICE_QUERY,
                    confidence=0.80,
                    evidence=f"title keyword '{kw}' matched as voice_query",
                    method="rule",
                )

        for kw in reflection_keywords:
            if kw in title_lower:
                return ClassificationResult(
                    scope=InputScope.REFLECTION,
                    confidence=0.80,
                    evidence=f"title keyword '{kw}' matched as reflection",
                    method="rule",
                )

        for kw in meeting_keywords:
            if kw in title_lower:
                return ClassificationResult(
                    scope=InputScope.MEETING,
                    confidence=0.75,
                    evidence=f"title keyword '{kw}' matched as meeting",
                    method="rule",
                )

        for kw in call_keywords:
            if kw in title_lower:
                return ClassificationResult(
                    scope=InputScope.CALL,
                    confidence=0.75,
                    evidence=f"title keyword '{kw}' matched as call",
                    method="rule",
                )

        return None

    async def _llm_classify(self, event: Event) -> ClassificationResult:
        """LLM-based classification as fallback when rules are insufficient."""
        raw_text_preview = (event.raw_text or "")[:200]

        prompt = (
            "你是一个输入分类器。将以下事件归类为8种输入范围之一。\n\n"
            "范围列表:\n"
            "- card_scan: 名片扫描录入\n"
            "- meeting: 会议/面谈记录\n"
            "- call: 电话/语音沟通\n"
            "- manual: 手动通用录入\n"
            "- followup: 跟进/提醒类\n"
            "- voice_query: 语音查询指令(F-50)\n"
            "- reflection: 回顾/总结/复盘\n"
            "- unknown: 无法确定\n\n"
            f"事件信息:\n"
            f"- 类型: {event.event_type}\n"
            f"- 来源: {event.source}\n"
            f"- 标题: {event.title}\n"
            f"- 内容摘要: {raw_text_preview}\n\n"
            '只返回JSON: {"scope": "xxx", "confidence": 0.xx, "evidence": "理由"}'
        )

        try:
            response = await self.llm.call_json(prompt=prompt, temperature=0.1)
        except Exception as exc:
            logger.warning(
                "llm_classify_failed",
                event_id=str(event.id),
                error=str(exc)[:200],
            )
            return ClassificationResult(
                scope=InputScope.UNKNOWN,
                confidence=0.30,
                evidence=f"LLM classification failed: {str(exc)[:100]}",
                method="llm",
            )

        # Parse response
        try:
            scope_str = response.get("scope", "unknown")
            confidence = float(response.get("confidence", 0.5))
            evidence = str(response.get("evidence", ""))

            # Clamp confidence to [0, 1]
            confidence = max(0.0, min(1.0, confidence))

            # Map string to enum
            try:
                scope = InputScope(scope_str)
            except ValueError:
                logger.warning(
                    "llm_invalid_scope",
                    event_id=str(event.id),
                    raw_scope=scope_str,
                )
                scope = InputScope.UNKNOWN
                evidence = f"LLM returned invalid scope '{scope_str}', defaulted to unknown"

            return ClassificationResult(
                scope=scope,
                confidence=confidence,
                evidence=evidence or "LLM classified",
                method="llm",
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "llm_response_parse_error",
                event_id=str(event.id),
                error=str(exc)[:200],
            )
            return ClassificationResult(
                scope=InputScope.UNKNOWN,
                confidence=0.20,
                evidence=f"Failed to parse LLM response: {str(exc)[:100]}",
                method="llm",
            )
