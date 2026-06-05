"""Promise Bidirectional Handler — F-45: Analyze todo promises to determine bidirectional action type.

Implements 6 action types (v4.4):
- my_promise: 我承诺(我答应对方)
- their_promise: 对方承诺(对方答应我)
- my_followup: 我跟进(主动联系)
- mutual_action: 双方共同行动
- system_reminder: 系统自动提醒
- unclear: 不明确

Strategy:
1. Rule-based: Check todo_type and title keywords first (high confidence patterns)
2. LLM fallback: If rules ambiguous (confidence < 0.80), use LLM analysis
3. Entity mapping: Map entities to promisor/beneficiary based on analysis result
4. Evidence extraction: Extract direct quote from event text supporting the promise
"""

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo

logger = get_logger("eventlink.promise_bidirectional")


class ActionType(str, Enum):
    """6 types of promise directionality for F-45 bidirectional model."""

    MY_PROMISE = "my_promise"  # 我承诺(我答应对方)
    THEIR_PROMISE = "their_promise"  # 对方承诺(对方答应我)
    MY_FOLLOWUP = "my_followup"  # 我跟进(主动联系)
    MUTUAL_ACTION = "mutual_action"  # 双方共同行动
    SYSTEM_REMINDER = "system_reminder"  # 系统自动提醒
    UNCLEAR = "unclear"  # 不明确


class ConfirmationStatus(str, Enum):
    """Confirmation status for AI-inferred vs rule-based results."""

    PENDING = "pending"  # 待确认(用户未确认AI推断)
    CONFIRMED = "confirmed"  # 用户确认
    REJECTED = "rejected"  # 用户否认
    AUTO_SET = "auto_set"  # 系统自动设置(非AI推断)


@dataclass
class PromiseAnalysis:
    """Result of promise directionality analysis."""

    action_type: ActionType
    promisor_entity_id: uuid.UUID | None = None  # 承诺者实体ID
    beneficiary_entity_id: uuid.UUID | None = None  # 受益者实体ID
    confirmation_status: ConfirmationStatus = ConfirmationStatus.PENDING
    evidence_quote: str | None = None  # 原文引用证据
    is_my_promise: bool = False  # 是否是"我"的承诺(用于view=my-responses过滤)
    confidence: float = 0.0  # 规则匹配或LLM返回的置信度


# Rule pattern definitions: (pattern, action_type, confidence)
# Ordered by priority (higher confidence first, more specific patterns first)
RULE_PATTERNS: list[tuple[re.Pattern, ActionType, float]] = [
    # System reminders (highest confidence)
    (re.compile(r"系统(?:提醒|通知|推送)"), ActionType.SYSTEM_REMINDER, 0.95),
    # My promises - first person commitments
    (
        re.compile(r"我(?:答应|承诺|说好|会|负责)"),
        ActionType.MY_PROMISE,
        0.92,
    ),
    # Mutual action - collaborative activities (check before their_promise to avoid false matches)
    (
        re.compile(r"(?:一起|合作|协同|配合)"),
        ActionType.MUTUAL_ACTION,
        0.85,
    ),
    # Their promises - other party commitments
    (
        re.compile(
            r"(?:他|她|它|对方|[\u4e00-\u9fa5]{1,4})(?:说|答应|承诺|会|提到)(?:\s*要)?"
        ),
        ActionType.THEIR_PROMISE,
        0.90,
    ),
    # My followup - proactive contact
    (
        re.compile(r"(?:关注|关心|跟进|回访)\s*一下"),
        ActionType.MY_FOLLOWUP,
        0.88,
    ),
]

# Todo type to action type mapping (when no keyword match)
TODO_TYPE_MAPPING: dict[str, tuple[ActionType, float]] = {
    "help": (ActionType.MY_FOLLOWUP, 0.82),
    "risk": (ActionType.SYSTEM_REMINDER, 0.80),
    "care": (ActionType.MY_FOLLOWUP, 0.80),  # Raised to 0.80 to pass threshold
    "cooperation_signal": (ActionType.MUTUAL_ACTION, 0.83),
}


class PromiseBidirectionalHandler:
    """F-45: Analyze todo promises to determine bidirectional action type.

    Uses a hybrid approach:
    1. Rule-based matching for high-confidence patterns (confidence >= 0.80)
    2. LLM-based analysis for ambiguous cases (confidence < 0.80)
    3. Entity resolution to map promisor/beneficiary from entity list
    4. Evidence extraction from event raw_text
    """

    def __init__(self, llm_client) -> None:
        """Initialize with LLM client for fallback analysis.

        Args:
            llm_client: LLMClient instance for LLM-based analysis.
        """
        self.llm_client = llm_client

    async def analyze_todo(
        self,
        todo: Todo,
        event: Event | None = None,
        entities: list[Entity] | None = None,
    ) -> PromiseAnalysis:
        """Analyze a todo to determine its promise directionality.

        Args:
            todo: The todo item to analyze.
            event: Optional source event for context and evidence extraction.
            entities: Optional list of related entities for promisor/beneficiary mapping.

        Returns:
            PromiseAnalysis with action_type, entity IDs, confirmation status, and evidence.
        """
        logger.info(
            "analyze_todo_start",
            todo_id=str(todo.id),
            todo_type=todo.todo_type,
            title=todo.title[:50],
        )

        # Step 1: Try rule-based analysis
        analysis = self._rule_analyze(todo)

        if analysis is not None and analysis.confidence >= 0.80:
            logger.info(
                "rule_based_match",
                todo_id=str(todo.id),
                action_type=analysis.action_type.value,
                confidence=analysis.confidence,
            )
            # Rule-based results are auto-set (not AI inference)
            analysis.confirmation_status = ConfirmationStatus.AUTO_SET
        else:
            # Step 2: Fall back to LLM analysis
            logger.info(
                "llm_fallback",
                todo_id=str(todo.id),
                reason="low_confidence_or_no_match",
            )
            analysis = await self._llm_analyze(todo, event)
            # LLM results need user confirmation
            analysis.confirmation_status = ConfirmationStatus.PENDING

        # Step 3: Extract evidence quote if not already set
        if analysis.evidence_quote is None:
            analysis.evidence_quote = self._extract_evidence(todo, event)

        # Step 4: Map entities to promisor/beneficiary
        if entities:
            self._map_entities(analysis, todo, entities)

        # Step 5: Set is_my_promise flag for view filtering
        analysis.is_my_promise = analysis.action_type in (
            ActionType.MY_PROMISE,
            ActionType.MY_FOLLOWUP,
        )

        logger.info(
            "analyze_todo_complete",
            todo_id=str(todo.id),
            action_type=analysis.action_type.value,
            confirmation_status=analysis.confirmation_status.value,
        )

        return analysis

    def _rule_analyze(self, todo: Todo) -> PromiseAnalysis | None:
        """Rule-based promise direction analysis.

        Checks todo title and description against predefined patterns.
        Returns None if no pattern matches or all matches have low confidence.

        Args:
            todo: The todo item to analyze.

        Returns:
            PromiseAnalysis if a high-confidence rule matches, else None.
        """
        # Combine title and description for matching
        text = f"{todo.title} {(todo.description or '')}"

        best_match: PromiseAnalysis | None = None
        best_confidence = 0.0

        # Check keyword patterns
        for pattern, action_type, confidence in RULE_PATTERNS:
            if pattern.search(text):
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = PromiseAnalysis(
                        action_type=action_type,
                        confidence=confidence,
                    )

        # Check todo_type mapping (lower priority than keywords)
        if todo.todo_type in TODO_TYPE_MAPPING:
            action_type, type_confidence = TODO_TYPE_MAPPING[todo.todo_type]
            if type_confidence > best_confidence:
                best_confidence = type_confidence
                best_match = PromiseAnalysis(
                    action_type=action_type,
                    confidence=type_confidence,
                )

        return best_match

    async def _llm_analyze(
        self, todo: Todo, event: Event | None
    ) -> PromiseAnalysis:
        """LLM-based analysis fallback for ambiguous cases.

        Constructs a prompt asking the LLM to determine:
        1. Action type (who made the promise?)
        2. Promisor and beneficiary identification
        3. Evidence quote from original text

        Args:
            todo: The todo item to analyze.
            event: Optional source event for context.

        Returns:
            PromiseAnalysis from LLM response.
        """
        event_raw_text = event.raw_text if event else "无关联事件"
        entity_names = []  # Will be populated by caller via _map_entities

        prompt = f"""分析以下待办事项的承诺方向性。

待办: {todo.title}
类型: {todo.todo_type}
描述: {todo.description or '无描述'}
原始事件: {event_raw_text[:300]}
相关人物: {', '.join(entity_names) if entity_names else '未知'}

判断:
1. 这是谁的承诺? (my_promise=我的, their_promise=对方的)
2. 谁是承诺者(promisor)? 谁是受益者(beneficiary)?
3. 原文中哪句话支持这个判断?(作为evidence_quote)

只返回JSON: {{
  "action_type": "my_promise|their_promise|my_followup|mutual_action|system_reminder|unclear",
  "promisor": "承诺者名字或null",
  "beneficiary": "受益者名字或null",
  "evidence_quote": "原文引用或null",
  "confidence": 0.xx
}}"""

        try:
            result = await self.llm_client.call_json(prompt)

            # Parse LLM response
            action_type_str = result.get("action_type", "unclear")
            try:
                action_type = ActionType(action_type_str)
            except ValueError:
                action_type = ActionType.UNCLEAR

            confidence = float(result.get("confidence", 0.5))

            return PromiseAnalysis(
                action_type=action_type,
                evidence_quote=result.get("evidence_quote"),
                confidence=confidence,
            )
        except Exception as e:
            logger.error(
                "llm_analyze_failed",
                todo_id=str(todo.id),
                error=str(e),
                exc_info=True,
            )
            # Return unclear on LLM failure
            return PromiseAnalysis(
                action_type=ActionType.UNCLEAR,
                confidence=0.0,
            )

    @staticmethod
    def _extract_evidence(todo: Todo, event: Event | None) -> str | None:
        """Extract direct quote from event text that supports the promise.

        Looks for sentences in event.raw_text that contain keywords from
        the todo title or describe commitment language.

        Args:
            todo: The todo item being analyzed.
            event: Optional source event to extract evidence from.

        Returns:
            Extracted evidence quote string, or None if no evidence found.
        """
        if not event or not event.raw_text:
            return None

        raw_text = event.raw_text

        # Try to find sentence containing todo title keywords
        # Split into sentences (Chinese punctuation)
        sentences = re.split(r'[。！？\n]', raw_text)

        # Extract key words from todo title (remove common words)
        title_words = set(re.findall(r'[\u4e00-\u9fa5]{2,}', todo.title))

        # Commitment-related words to boost scoring
        commitment_words = {'答应', '承诺', '说好', '会', '负责', '提交', '给', '发送', '完成'}

        best_sentence = None
        best_score = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 5:
                continue

            # Count how many title words appear in this sentence
            matched_words = sum(1 for word in title_words if word in sentence)
            # Bonus for commitment words
            commitment_matches = sum(1 for word in commitment_words if word in sentence)

            score = matched_words * 2 + commitment_matches * 3

            if score > best_score:
                best_score = score
                best_sentence = sentence

        if best_sentence and best_score > 0:
            return best_sentence[:200]  # Limit length

        # Fallback: return first meaningful sentence
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) >= 10:
                return sentence[:200]

        return None

    @staticmethod
    def _map_entities(
        analysis: PromiseAnalysis,
        todo: Todo,
        entities: list[Entity],
    ) -> None:
        """Map entities to promisor/beneficiary based on action type.

        Uses heuristics to assign entity IDs:
        - my_promise/my_followup: user's entity → promisor, related_entity → beneficiary
        - their_promise: related_entity → promisor, user's entity → beneficiary
        - mutual_action: both entities involved
        - system_reminder: no specific entity assignment

        Args:
            analysis: The analysis result to update.
            todo: The original todo item.
            entities: List of available entities.
        """
        if not entities:
            return

        # Find the entity referenced by the todo (if any)
        related_entity = None
        if todo.related_entity_id:
            related_entity = next(
                (e for e in entities if e.id == todo.related_entity_id), None
            )

        if analysis.action_type == ActionType.MY_PROMISE:
            # I promised → I am promisor, they are beneficiary
            analysis.promisor_entity_id = None  # User entity (implicit)
            analysis.beneficiary_entity_id = (
                related_entity.id if related_entity else (entities[0].id if entities else None)
            )

        elif analysis.action_type == ActionType.THEIR_PROMISE:
            # They promised → They are promisor, I am beneficiary
            analysis.promisor_entity_id = (
                related_entity.id if related_entity else (entities[0].id if entities else None)
            )
            analysis.beneficiary_entity_id = None  # User entity (implicit)

        elif analysis.action_type == ActionType.MY_FOLLOWUP:
            # I am following up → I am actor, they are target
            analysis.promisor_entity_id = None  # User entity (implicit)
            analysis.beneficiary_entity_id = (
                related_entity.id if related_entity else (entities[0].id if entities else None)
            )

        elif analysis.action_type == ActionType.MUTUAL_ACTION:
            # Both parties involved
            if len(entities) >= 1:
                analysis.promisor_entity_id = entities[0].id
            if len(entities) >= 2:
                analysis.beneficiary_entity_id = entities[1].id
            elif related_entity:
                analysis.beneficiary_entity_id = related_entity.id

        # system_reminder and unclear: no entity mapping needed
