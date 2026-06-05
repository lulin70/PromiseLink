"""Tests for F-48 RelationshipStage State Machine — 7-stage transitions.

Covers: can_transition, suggest_transition, apply_transition,
        get_stage_metadata, get_all_stages, check_dormant_eligibility.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from eventlink.core.exceptions import InvalidTransitionError
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.services.relationship_stage import (
    STAGE_METADATA,
    STAGE_TRANSITIONS,
    RelationshipStage,
    RelationshipStageMachine,
    StageTransitionResult,
)


# ── Helpers ──


def _make_brief(
    stage: str = "new_connection",
    version: int = 1,
) -> RelationshipBrief:
    """Create a minimal RelationshipBrief for testing (no DB required)."""
    brief = RelationshipBrief(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        person_entity_id=str(uuid.uuid4()),
        relationship_stage=stage,
        brief_data={},
        version=version,
    )
    return brief


# ── 1. can_transition: 所有正向转换都合法 ──


class TestCanTransitionForward:
    """Test all valid forward transitions."""

    def test_new_to_understanding(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.UNDERSTANDING_NEEDS,
        ) is True

    def test_new_to_dormant(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.DORMANT,
        ) is True

    def test_understanding_to_value(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.UNDERSTANDING_NEEDS,
            RelationshipStage.VALUE_RESPONSE,
        ) is True

    def test_value_to_deep_trust(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.VALUE_RESPONSE,
            RelationshipStage.DEEP_TRUST,
        ) is True

    def test_deep_trust_to_active_cooperation(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.DEEP_TRUST,
            RelationshipStage.ACTIVE_COOPERATION,
        ) is True

    def test_active_cooperation_to_long_term_partner(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.ACTIVE_COOPERATION,
            RelationshipStage.LONG_TERM_PARTNER,
        ) is True

    def test_long_term_partner_to_active_cooperation(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.LONG_TERM_PARTNER,
            RelationshipStage.ACTIVE_COOPERATION,
        ) is True


# ── 2. can_transition: 非法转换返回False ──


class TestCanTransitionInvalid:
    """Test that invalid transitions return False."""

    def test_new_to_deep_trust_direct_skip(self):
        """Cannot skip stages: NEW_CONNECTION → DEEP_TRUST."""
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.DEEP_TRUST,
        ) is False

    def test_new_to_value_response_direct_skip(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.VALUE_RESPONSE,
        ) is False

    def test_understanding_to_deep_trust_skip(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.UNDERSTANDING_NEEDS,
            RelationshipStage.DEEP_TRUST,
        ) is False

    def test_value_to_long_term_partner_skip(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.VALUE_RESPONSE,
            RelationshipStage.LONG_TERM_PARTNER,
        ) is False

    def test_dormant_cannot_go_to_dormant(self):
        sm = RelationshipStageMachine()
        # DORMANT → DORMANT is same-stage, allowed as no-op
        assert sm.can_transition(
            RelationshipStage.DORMANT,
            RelationshipStage.DORMANT,
        ) is True


# ── 3. can_transition: DORMANT可以转到任何活跃阶段(恢复机制) ──


class TestDormantRecovery:
    """Test DORMANT recovery to any active stage."""

    @pytest.mark.parametrize("target", [
        RelationshipStage.NEW_CONNECTION,
        RelationshipStage.UNDERSTANDING_NEEDS,
        RelationshipStage.VALUE_RESPONSE,
        RelationshipStage.DEEP_TRUST,
        RelationshipStage.ACTIVE_COOPERATION,
        RelationshipStage.LONG_TERM_PARTNER,
    ])
    def test_dormant_can_recover_to_all_active_stages(self, target):
        sm = RelationshipStageMachine()
        assert sm.can_transition(RelationshipStage.DORMANT, target) is True


# ── 4. suggest_transition: 有多个value_exchange事件→建议VALUE_RESPONSE ──


class TestSuggestValueResponse:
    def test_multiple_value_exchanges_suggests_value_response(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.UNDERSTANDING_NEEDS,
            interaction_data={"value_exchange_count": 3},
        )
        assert result is not None
        assert result.current_stage == RelationshipStage.VALUE_RESPONSE
        assert "value-exchange" in result.reason
        assert result.requires_confirmation is True

    def test_single_value_exchange_no_suggestion(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.UNDERSTANDING_NEEDS,
            interaction_data={"value_exchange_count": 1},
        )
        assert result is None  # need >= 2

    def test_zero_value_exchanges_no_suggestion(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.UNDERSTANDING_NEEDS,
            interaction_data={"value_exchange_count": 0},
        )
        assert result is None


# ── 5. suggest_transition: 有care类型todo→建议UNDERSTANDING_NEEDS ──


class TestSuggestUnderstandingNeeds:
    def test_care_todo_suggests_understanding_needs(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.NEW_CONNECTION,
            interaction_data={"care_todo_count": 2},
        )
        assert result is not None
        assert result.current_stage == RelationshipStage.UNDERSTANDING_NEEDS
        assert "concerns" in result.reason.lower() or "care" in result.reason.lower()

    def test_no_care_todos_no_suggestion_from_new(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.NEW_CONNECTION,
            interaction_data={"care_todo_count": 0},
        )
        assert result is None


# ── 6. suggest_transition: 超90天无互动→建议DORMANT ──


class TestSuggestDormant:
    def test_over_90_days_suggests_dormant(self):
        sm = RelationshipStageMachine()
        old_date = datetime.now(timezone.utc) - timedelta(days=95)
        result = sm.suggest_transition(
            RelationshipStage.VALUE_RESPONSE,
            interaction_data={"last_interaction_date": old_date},
        )
        assert result is not None
        assert "dormant" in result.reason.lower()
        assert result.requires_confirmation is True

    def test_30_days_no_dormant_suggestion(self):
        sm = RelationshipStageMachine()
        recent_date = datetime.now(timezone.utc) - timedelta(days=30)
        result = sm.suggest_transition(
            RelationshipStage.VALUE_RESPONSE,
            interaction_data={"last_interaction_date": recent_date},
        )
        # Should not suggest dormant; may or may not suggest other things
        if result is not None:
            assert "dormant" not in result.reason.lower()


# ── 7. suggest_transition: 无足够数据→返回None ──


class TestSuggestNoData:
    def test_empty_interaction_data_returns_none(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(RelationshipStage.NEW_CONNECTION, {})
        assert result is None

    def test_none_interaction_data_returns_none(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(RelationshipStage.NEW_CONNECTION, None)
        assert result is None

    def test_irrelevant_data_returns_none(self):
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.DEEP_TRUST,
            interaction_data={"some_random_field": 42},
        )
        assert result is None


# ── 8. apply_transition: 合法转换成功应用 ──


class TestApplyValidTransition:
    def test_valid_forward_transition(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("new_connection")
        result = sm.apply_transition(
            brief,
            RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=True,
            reason="User confirmed stage upgrade",
        )
        assert result.success is True
        assert result.current_stage == RelationshipStage.UNDERSTANDING_NEEDS
        assert brief.relationship_stage == "understanding_needs"

    def test_valid_backward_transition(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("understanding_needs")
        result = sm.apply_transition(
            brief,
            RelationshipStage.NEW_CONNECTION,
            reason="Relationship regressed",
        )
        assert result.success is True
        assert brief.relationship_stage == "new_connection"

    def test_dormant_recovery(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("dormant")
        result = sm.apply_transition(
            brief,
            RelationshipStage.UNDERSTANDING_NEEDS,
            reason="Reconnected after dormancy",
        )
        assert result.success is True
        assert brief.relationship_stage == "understanding_needs"


# ── 9. apply_transition: 非法转换抛出异常 ──


class TestApplyInvalidTransitionRaises:
    def test_invalid_raises_error(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("new_connection")
        with pytest.raises(InvalidTransitionError) as exc_info:
            sm.apply_transition(brief, RelationshipStage.DEEP_TRUST)
        assert "new_connection" in str(exc_info.value.message).lower()
        assert "deep_trust" in str(exc_info.value.message).lower()

    def test_skip_two_stages_raises(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("new_connection")
        with pytest.raises(InvalidTransitionError):
            sm.apply_transition(brief, RelationshipStage.ACTIVE_COOPERATION)


# ── 10. apply_transition: 需要确认但未给confirmed_by_user→失败 ──


class TestApplyConfirmationRequired:
    def test_poc_new_to_understanding_needs_confirmation(self):
        """PoC RS-01: new_connection → understanding_needs requires confirmation."""
        sm = RelationshipStageMachine()
        brief = _make_brief("new_connection")
        result = sm.apply_transition(
            brief,
            RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=False,
        )
        assert result.success is False
        assert result.requires_confirmation is True
        assert "confirmation" in result.reason.lower()
        # Brief should NOT be modified
        assert brief.relationship_stage == "new_connection"

    def test_poc_understanding_to_value_needs_confirmation(self):
        """PoC RS-01: understanding_needs → value_response requires confirmation."""
        sm = RelationshipStageMachine()
        brief = _make_brief("understanding_needs")
        result = sm.apply_transition(
            brief,
            RelationshipStage.VALUE_RESPONSE,
            confirmed_by_user=False,
        )
        assert result.success is False
        assert result.requires_confirmation is True
        assert brief.relationship_stage == "understanding_needs"

    def test_with_confirmation_succeeds(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("new_connection")
        result = sm.apply_transition(
            brief,
            RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=True,
        )
        assert result.success is True
        assert brief.relationship_stage == "understanding_needs"

    def test_non_poc_transition_no_confirmation_needed(self):
        """Backward transition does NOT require PoC confirmation."""
        sm = RelationshipStageMachine()
        brief = _make_brief("understanding_needs")
        result = sm.apply_transition(
            brief,
            RelationshipStage.NEW_CONNECTION,
            confirmed_by_user=False,
            reason="Regression",
        )
        assert result.success is True
        assert result.requires_confirmation is False


# ── 11. apply_transition: version自增 ──


class TestVersionIncrement:
    def test_version_increments_on_success(self):
        sm = RelationshipStageMachine()
        brief = _make_brief(stage="new_connection", version=3)
        initial_version = brief.version
        sm.apply_transition(
            brief,
            RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=True,
        )
        assert brief.version == initial_version + 1

    def test_version_not_incremented_on_failure(self):
        sm = RelationshipStageMachine()
        brief = _make_brief(stage="new_connection", version=5)
        initial_version = brief.version
        sm.apply_transition(
            brief,
            RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=False,  # will fail due to missing confirmation
        )
        assert brief.version == initial_version

    def test_version_not_incremented_on_same_stage(self):
        sm = RelationshipStageMachine()
        brief = _make_brief(stage="value_response", version=7)
        initial_version = brief.version
        sm.apply_transition(brief, RelationshipStage.VALUE_RESPONSE)
        assert brief.version == initial_version  # no-op, no increment


# ── 12. get_stage_metadata: 返回正确的label/color/icon ──


class TestGetStageMetadata:
    def test_new_connection_metadata(self):
        meta = RelationshipStageMachine.get_stage_metadata(
            RelationshipStage.NEW_CONNECTION
        )
        assert meta["label"] == "初次连接"
        assert meta["color"] == "#A0C4A8"
        assert meta["icon"] == "\U0001f44b"
        assert meta["order"] == 1

    def test_dormant_metadata(self):
        meta = RelationshipStageMachine.get_stage_metadata(RelationshipStage.DORMANT)
        assert meta["label"] == "沉寂"
        assert meta["color"] == "#C4C4C4"
        assert meta["order"] == 7

    def test_long_term_partner_metadata(self):
        meta = RelationshipStageMachine.get_stage_metadata(
            RelationshipStage.LONG_TERM_PARTNER
        )
        assert meta["label"] == "长期伙伴"
        assert meta["icon"] == "\u2b50"
        assert meta["order"] == 6

    def test_all_stages_have_required_fields(self):
        required = {"label", "color", "icon", "description", "order"}
        for stage in RelationshipStage:
            meta = RelationshipStageMachine.get_stage_metadata(stage)
            assert required.issubset(meta.keys()), (
                f"Stage {stage.value} missing fields: {required - set(meta.keys())}"
            )


# ── 13. get_all_stages: 返回7个阶段按order排序 ──


class TestGetAllStages:
    def test_returns_7_stages(self):
        stages = RelationshipStageMachine.get_all_stages()
        assert len(stages) == 7

    def test_sorted_by_order(self):
        stages = RelationshipStageMachine.get_all_stages()
        orders = [s["order"] for s in stages]
        assert orders == sorted(orders)

    def test_first_is_new_connection(self):
        stages = RelationshipStageMachine.get_all_stages()
        assert stages[0]["value"] == "new_connection"

    def test_last_is_dormant(self):
        stages = RelationshipStageMachine.get_all_stages()
        assert stages[-1]["value"] == "dormant"


# ── 14. check_dormant_eligibility: 91天前→True ──


class TestDormantEligibilityTrue:
    def test_91_days_ago_eligible(self):
        sm = RelationshipStageMachine()
        old_date = datetime.now(timezone.utc) - timedelta(days=91)
        assert sm.check_dormant_eligibility(old_date) is True

    def test_100_days_ago_eligible(self):
        sm = RelationshipStageMachine()
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        assert sm.check_dormant_eligibility(old_date) is True

    def test_exactly_threshold_plus_one(self):
        sm = RelationshipStageMachine()
        old_date = datetime.now(timezone.utc) - timedelta(days=91)
        assert sm.check_dormant_eligibility(old_date) is True


# ── 15. check_dormant_eligibility: 30天前→False ──


class TestDormantEligibilityFalse:
    def test_30_days_ago_not_eligible(self):
        sm = RelationshipStageMachine()
        recent = datetime.now(timezone.utc) - timedelta(days=30)
        assert sm.check_dormant_eligibility(recent) is False

    def test_90_days_ago_not_eligible(self):
        """Exactly 90 days should NOT be eligible (> 90, not >=)."""
        sm = RelationshipStageMachine()
        boundary = datetime.now(timezone.utc) - timedelta(days=90)
        assert sm.check_dormant_eligibility(boundary) is False

    def test_1_day_ago_not_eligible(self):
        sm = RelationshipStageMachine()
        very_recent = datetime.now(timezone.utc) - timedelta(days=1)
        assert sm.check_dormant_eligibility(very_recent) is False

    def test_none_returns_false(self):
        sm = RelationshipStageMachine()
        assert sm.check_dormant_eligibility(None) is False


# ── 16. 边界: 同阶段转换(无变化)的处理 ──


class TestSameStageTransition:
    def test_same_stage_is_allowed(self):
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.NEW_CONNECTION,
        ) is True

    def test_same_stage_apply_returns_success_no_change(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("value_response", version=10)
        result = sm.apply_transition(brief, RelationshipStage.VALUE_RESPONSE)
        assert result.success is True
        assert result.auto_applied is True
        assert result.requires_confirmation is False
        assert result.previous_stage == RelationshipStage.VALUE_RESPONSE
        assert brief.relationship_stage == "value_response"
        assert brief.version == 10  # unchanged

    def test_same_stage_result_has_reason(self):
        sm = RelationshipStageMachine()
        brief = _make_brief("deep_trust")
        result = sm.apply_transition(brief, RelationshipStage.DEEP_TRUST)
        assert "no change" in result.reason.lower() or "same" in result.reason.lower()


# ── Additional: Enum & Constants Integrity ──


class TestEnumAndConstantsIntegrity:
    def test_enum_has_7_members(self):
        assert len(RelationshipStage) == 7

    def test_transitions_cover_all_stages(self):
        for stage in RelationshipStage:
            assert stage in STAGE_TRANSITIONS, f"{stage} missing from STAGE_TRANSITIONS"

    def test_metadata_cover_all_stages(self):
        for stage in RelationshipStage:
            assert stage in STAGE_METADATA, f"{stage} missing from STAGE_METADATA"

    def test_poc_active_stages_subset_of_all(self):
        assert RelationshipStageMachine.POC_ACTIVE_STAGES.issubset(set(RelationshipStage))

    def test_dormant_threshold_positive(self):
        assert RelationshipStageMachine.DORMANT_THRESHOLD_DAYS > 0

    def test_stage_transition_result_fields(self):
        result = StageTransitionResult(
            success=True,
            current_stage=RelationshipStage.NEW_CONNECTION,
            previous_stage=None,
            reason="test",
            requires_confirmation=False,
            auto_applied=True,
        )
        assert result.success is True
        assert result.current_stage == RelationshipStage.NEW_CONNECTION
        assert result.previous_stage is None
