"""F-48: RelationshipStage State Machine Service.

Algorithm_Design §6 — 7-stage relationship lifecycle:
  new_connection → understanding_needs → value_response → deep_trust →
  active_cooperation → long_term_partner ↔ dormant

PoC scope: first 3 stages with user-confirmation-required (RS-01).
Phase 1+: heuristic suggestions + LLM-assisted transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from promiselink.models.relationship_brief import RelationshipBrief

from promiselink.core.exceptions import InvalidTransitionError


# ── Stage Enumeration ──


class RelationshipStage(str, Enum):
    """7 stages of relationship progression."""

    NEW_CONNECTION = "new_connection"
    UNDERSTANDING_NEEDS = "understanding_needs"
    VALUE_RESPONSE = "value_response"
    DEEP_TRUST = "deep_trust"
    ACTIVE_COOPERATION = "active_cooperation"
    LONG_TERM_PARTNER = "long_term_partner"
    DORMANT = "dormant"


# ── Valid State Transitions ──


STAGE_TRANSITIONS: dict[RelationshipStage, set[RelationshipStage]] = {
    RelationshipStage.NEW_CONNECTION: {
        RelationshipStage.UNDERSTANDING_NEEDS,
        RelationshipStage.DORMANT,
    },
    RelationshipStage.UNDERSTANDING_NEEDS: {
        RelationshipStage.VALUE_RESPONSE,
        RelationshipStage.NEW_CONNECTION,
        RelationshipStage.DORMANT,
    },
    RelationshipStage.VALUE_RESPONSE: {
        RelationshipStage.DEEP_TRUST,
        RelationshipStage.UNDERSTANDING_NEEDS,
        RelationshipStage.DORMANT,
    },
    RelationshipStage.DEEP_TRUST: {
        RelationshipStage.ACTIVE_COOPERATION,
        RelationshipStage.VALUE_RESPONSE,
        RelationshipStage.DORMANT,
    },
    RelationshipStage.ACTIVE_COOPERATION: {
        RelationshipStage.LONG_TERM_PARTNER,
        RelationshipStage.DEEP_TRUST,
        RelationshipStage.DORMANT,
    },
    RelationshipStage.LONG_TERM_PARTNER: {
        RelationshipStage.ACTIVE_COOPERATION,
        RelationshipStage.DORMANT,
    },
    # DORMANT can recover to any active stage (requires explicit target)
    RelationshipStage.DORMANT: set(),
}

# All non-dormant stages that DORMANT can recover to
_DORMANT_RECOVERY_TARGETS: frozenset[RelationshipStage] = frozenset({
    RelationshipStage.NEW_CONNECTION,
    RelationshipStage.UNDERSTANDING_NEEDS,
    RelationshipStage.VALUE_RESPONSE,
    RelationshipStage.DEEP_TRUST,
    RelationshipStage.ACTIVE_COOPERATION,
    RelationshipStage.LONG_TERM_PARTNER,
})


# ── Stage Metadata (UI display) ──


STAGE_METADATA: dict[RelationshipStage, dict[str, Any]] = {
    RelationshipStage.NEW_CONNECTION: {
        "label": "初次连接",
        "color": "#A0C4A8",
        "icon": "\U0001f44b",
        "description": "刚建立联系，正在互相了解",
        "order": 1,
    },
    RelationshipStage.UNDERSTANDING_NEEDS: {
        "label": "了解需求",
        "color": "#A0B0C4",
        "icon": "\U0001f50d",
        "description": "知道对方关心什么，理解其业务痛点",
        "order": 2,
    },
    RelationshipStage.VALUE_RESPONSE: {
        "label": "价值回应",
        "color": "#C4C0A0",
        "icon": "\U0001f91d",
        "description": "已为对方提供帮助或价值，获得正面反馈",
        "order": 3,
    },
    RelationshipStage.DEEP_TRUST: {
        "label": "深度信任",
        "color": "#B0A0C4",
        "icon": "\U0001f48e",
        "description": "多次互惠往来，建立了深度信任关系",
        "order": 4,
    },
    RelationshipStage.ACTIVE_COOPERATION: {
        "label": "积极合作",
        "color": "#B8C4C0",
        "icon": "\U0001f91d",
        "description": "正在进行正式的项目或商业合作",
        "order": 5,
    },
    RelationshipStage.LONG_TERM_PARTNER: {
        "label": "长期伙伴",
        "color": "#C4A0A0",
        "icon": "\u2b50",
        "description": "稳定的长期合作伙伴关系",
        "order": 6,
    },
    RelationshipStage.DORMANT: {
        "label": "沉寂",
        "color": "#C4C4C4",
        "icon": "\U0001f4a4",
        "description": "长期未联系，关系进入休眠状态",
        "order": 7,
    },
}


# ── Transition Result ──


@dataclass
class StageTransitionResult:
    """Result of a stage transition attempt."""

    success: bool
    current_stage: RelationshipStage
    previous_stage: RelationshipStage | None
    reason: str
    requires_confirmation: bool
    auto_applied: bool


# ── PoC Confirmation Rules ──


# Transitions that require explicit user confirmation in PoC phase
_POC_CONFIRM_REQUIRED: frozenset[tuple[RelationshipStage, RelationshipStage]] = frozenset({
    (RelationshipStage.NEW_CONNECTION, RelationshipStage.UNDERSTANDING_NEEDS),
    (RelationshipStage.UNDERSTANDING_NEEDS, RelationshipStage.VALUE_RESPONSE),
})


# ── State Machine ──


class RelationshipStageMachine:
    """F-48: State machine for relationship stage transitions.

    Enforces valid transitions per STAGE_TRANSITIONS table and manages
    the full stage lifecycle including dormant detection and recovery.
    """

    POC_ACTIVE_STAGES = frozenset({
        RelationshipStage.NEW_CONNECTION,
        RelationshipStage.UNDERSTANDING_NEEDS,
        RelationshipStage.VALUE_RESPONSE,
    })

    DORMANT_THRESHOLD_DAYS = 90

    def __init__(self) -> None:
        pass

    # ── Validation ──

    def can_transition(
        self,
        from_stage: RelationshipStage,
        to_stage: RelationshipStage,
    ) -> bool:
        """Check if transition is valid per STAGE_TRANSITIONS table.

        DORMANT is a special case: it can recover to any active stage.
        """
        if from_stage == to_stage:
            return True  # same-stage is a no-op, allowed

        if from_stage == RelationshipStage.DORMANT:
            return to_stage in _DORMANT_RECOVERY_TARGETS

        return to_stage in STAGE_TRANSITIONS.get(from_stage, set())

    # ── Suggestion Heuristics ──

    def suggest_transition(
        self,
        current_stage: RelationshipStage,
        interaction_data: dict | None = None,
    ) -> StageTransitionResult | None:
        """Suggest next stage based on interaction data.

        Heuristic rules (no LLM for PoC):
          1. Multiple value-exchange events → suggest VALUE_RESPONSE
          2. Care-type todos exist (knows concerns) → suggest UNDERSTANDING_NEEDS
          3. No contact > DORMANT_THRESHOLD_DAYS → suggest DORMANT

        Returns None if no suggestion is applicable.
        """
        data = interaction_data or {}

        # Rule 3: Inactivity check (highest priority for existing relationships)
        last_interaction = data.get("last_interaction_date")
        if last_interaction is not None:
            if isinstance(last_interaction, str):
                last_interaction = datetime.fromisoformat(last_interaction)
            if self.check_dormant_eligibility(last_interaction):
                return StageTransitionResult(
                    success=False,
                    current_stage=current_stage,
                    previous_stage=None,
                    reason=(
                        f"No interaction for >{self.DORMANT_THRESHOLD_DAYS} days; "
                        "suggest marking as dormant"
                    ),
                    requires_confirmation=True,
                    auto_applied=False,
                )

        # Rule 1: Value-exchange events suggest VALUE_RESPONSE
        value_exchange_count = data.get("value_exchange_count", 0)
        if (
            current_stage == RelationshipStage.UNDERSTANDING_NEEDS
            and isinstance(value_exchange_count, int)
            and value_exchange_count >= 2
        ):
            return StageTransitionResult(
                success=False,
                current_stage=RelationshipStage.VALUE_RESPONSE,
                previous_stage=current_stage,
                reason="Multiple value-exchange events detected",
                requires_confirmation=True,
                auto_applied=False,
            )

        # Rule 2: Care todos suggest UNDERSTANDING_NEEDS
        care_todo_count = data.get("care_todo_count", 0)
        if (
            current_stage == RelationshipStage.NEW_CONNECTION
            and isinstance(care_todo_count, int)
            and care_todo_count >= 1
        ):
            return StageTransitionResult(
                success=False,
                current_stage=RelationshipStage.UNDERSTANDING_NEEDS,
                previous_stage=current_stage,
                reason="Care-type todo exists (knows concerns)",
                requires_confirmation=True,
                auto_applied=False,
            )

        return None

    # ── Apply Transition ──

    def apply_transition(
        self,
        brief: RelationshipBrief,
        to_stage: RelationshipStage,
        confirmed_by_user: bool = False,
        reason: str = "",
    ) -> StageTransitionResult:
        """Apply a stage transition to a RelationshipBrief.

        Validates transition legality, checks confirmation requirements,
        updates stage on the brief, and increments version.

        Args:
            brief: The relationship brief to update.
            to_stage: Target stage.
            confirmed_by_user: Whether user has explicitly confirmed.
            reason: Human-readable reason for the transition.

        Returns:
            StageTransitionResult with outcome details.

        Raises:
            InvalidTransitionError: If the transition is not valid.
        """
        from_stage_str = brief.relationship_stage
        try:
            from_stage = RelationshipStage(from_stage_str)
        except ValueError:
            raise InvalidTransitionError(from_stage_str, to_stage.value)

        # Same-stage no-op
        if from_stage == to_stage:
            return StageTransitionResult(
                success=True,
                current_stage=to_stage,
                previous_stage=from_stage,
                reason=reason or "No change (same stage)",
                requires_confirmation=False,
                auto_applied=True,
            )

        # Validate legality
        if not self.can_transition(from_stage, to_stage):
            raise InvalidTransitionError(from_stage.value, to_stage.value)

        # Check PoC confirmation requirement
        needs_confirm = (from_stage, to_stage) in _POC_CONFIRM_REQUIRED
        if needs_confirm and not confirmed_by_user:
            return StageTransitionResult(
                success=False,
                current_stage=from_stage,
                previous_stage=from_stage,
                reason=(
                    f"PoC: transition {from_stage.value} → {to_stage.value} "
                    "requires user confirmation (RS-01)"
                ),
                requires_confirmation=True,
                auto_applied=False,
            )

        # Apply
        previous_version = brief.version
        brief.relationship_stage = to_stage.value
        brief.version = previous_version + 1

        return StageTransitionResult(
            success=True,
            current_stage=to_stage,
            previous_stage=from_stage,
            reason=reason or f"Transitioned from {from_stage.value}",
            requires_confirmation=needs_confirm,
            auto_applied=not needs_confirm,
        )

    # ── Metadata Accessors ──

    @staticmethod
    def get_stage_metadata(stage: RelationshipStage) -> dict:
        """Get display metadata for a stage."""
        return dict(STAGE_METADATA.get(stage, {}))

    @classmethod
    def get_all_stages(cls) -> list[dict]:
        """Get all stages ordered by progression order."""
        stages = []
        for stage in RelationshipStage:
            meta = cls.get_stage_metadata(stage)
            meta["value"] = stage.value
            stages.append(meta)
        stages.sort(key=lambda s: s.get("order", 99))
        return stages

    # ── Dormant Detection ──

    def check_dormant_eligibility(self, last_interaction_date: datetime | None) -> bool:
        """Check if a relationship should be marked as dormant based on inactivity.

        Args:
            last_interaction_date: Last known interaction datetime (timezone-aware).

        Returns:
            True if the relationship is eligible for dormant status.
        """
        if last_interaction_date is None:
            return False

        now = datetime.now(timezone.utc)
        # Ensure comparison in UTC
        if last_interaction_date.tzinfo is None:
            last_interaction_date = last_interaction_date.replace(tzinfo=timezone.utc)

        delta = now - last_interaction_date
        return delta.days > self.DORMANT_THRESHOLD_DAYS
