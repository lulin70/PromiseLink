"""Unit tests for natural language date parser (natural_date.py)."""

from datetime import date, timedelta

import pytest

from promiselink.core.natural_date import (
    _generate_label,
    parse_natural_date,
)


class TestParseNaturalDate:
    """Tests for parse_natural_date main function."""

    @pytest.fixture(autouse=True)
    def _ref_date(self):
        """Use a fixed reference date for deterministic tests: 2026-06-04 (Thursday)."""
        self.ref = date(2026, 6, 4)

    # ── Test 1: None / default → today ──────────────────────────────

    def test_none_returns_today(self):
        result = parse_natural_date(None, reference_date=self.ref)
        assert result.start_date == self.ref
        assert result.end_date == self.ref
        assert not result.is_range

    def test_empty_string_returns_today(self):
        result = parse_natural_date("", reference_date=self.ref)
        assert result.start_date == self.ref

    # ── Test 2: 明天 → +1 day ───────────────────────────────────────

    def test_tomorrow(self):
        result = parse_natural_date("明天", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=1)

    # ── Test 3: 后天 → +2 days ──────────────────────────────────────

    def test_day_after_tomorrow(self):
        result = parse_natural_date("后天", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=2)

    # ── Test 4: 昨天 → -1 day ───────────────────────────────────────

    def test_yesterday(self):
        result = parse_natural_date("昨天", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=-1)

    # ── Test 5: ISO format YYYY-MM-DD ───────────────────────────────

    def test_iso_format(self):
        result = parse_natural_date("2026-06-04", reference_date=self.ref)
        assert result.start_date == date(2026, 6, 4)
        assert not result.is_range

    # ── Test 6: Relative days: 3天后 / +3 / 3d ─────────────────────

    def test_relative_days_chinese(self):
        result = parse_natural_date("3天后", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=3)

    def test_relative_days_plus_sign(self):
        result = parse_natural_date("+3", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=3)

    def test_relative_days_d_suffix(self):
        result = parse_natural_date("3d", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=3)

    # ── Test 7: Negative relative days ───────────────────────────────

    def test_negative_five_days(self):
        result = parse_natural_date("-5", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=-5)

    def test_negative_days_chinese(self):
        result = parse_natural_date("2天前", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=-2)

    # ── Test 8: 本周 → this week range ───────────────────────────────

    def test_this_week_is_range(self):
        result = parse_natural_date("本周", reference_date=self.ref)
        assert result.is_range
        # Thursday of that week → Monday is 3 days before
        expected_monday = self.ref - timedelta(days=self.ref.weekday())
        assert result.start_date == expected_monday
        assert result.end_date == expected_monday + timedelta(days=6)

    # ── Test 9: 下周 → next week range ──────────────────────────────

    def test_next_week_is_range(self):
        result = parse_natural_date("下周", reference_date=self.ref)
        assert result.is_range
        expected_monday = self.ref - timedelta(days=self.ref.weekday()) + timedelta(weeks=1)
        assert result.start_date == expected_monday
        assert result.end_date == expected_monday + timedelta(days=6)

    # ── Test 10: English keywords ────────────────────────────────────

    def test_english_today(self):
        result = parse_natural_date("today", reference_date=self.ref)
        assert result.start_date == self.ref

    def test_english_tomorrow(self):
        result = parse_natural_date("tomorrow", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=1)

    def test_english_yesterday(self):
        result = parse_natural_date("yesterday", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=-1)

    # ── Test 11: Label generation includes weekday ───────────────────

    def test_label_today_has_weekday(self):
        result = parse_natural_date(None, reference_date=self.ref)
        assert "周四" in result.label
        assert "今天" in result.label

    def test_label_tomorrow_has_weekday(self):
        result = parse_natural_date("明天", reference_date=self.ref)
        assert "周五" in result.label
        assert "明天" in result.label

    def test_label_iso_date_has_weekday(self):
        result = parse_natural_date("2026-06-10", reference_date=self.ref)  # Wednesday
        assert "周三" in result.label

    # ── Test 12: Invalid input raises ValueError ─────────────────────

    def test_invalid_input_raises_value_error(self):
        with pytest.raises(ValueError, match="无法解析日期表达式"):
            parse_natural_date("foobarbaz", reference_date=self.ref)

    def test_garbage_string_raises(self):
        with pytest.raises(ValueError):
            parse_natural_date("xyz123", reference_date=self.ref)

    # ── Test 13: Boundary: invalid ISO date ──────────────────────────

    def test_invalid_iso_date_raises(self):
        with pytest.raises((ValueError,)):
            parse_natural_date("9999-99-99", reference_date=self.ref)

    def test_invalid_month_raises(self):
        with pytest.raises((ValueError,)):
            parse_natural_date("2026-13-01", reference_date=self.ref)

    # ── Test 14: Custom reference_date ───────────────────────────────

    def test_custom_reference_date(self):
        custom_ref = date(2026, 1, 1)
        result = parse_natural_date("明天", reference_date=custom_ref)
        assert result.start_date == date(2026, 1, 2)

    def test_custom_reference_affects_label(self):
        custom_ref = date(2026, 1, 5)  # Monday
        result = parse_natural_date(None, reference_date=custom_ref)
        assert "周一" in result.label

    # ── Test 15: Case insensitive ────────────────────────────────────

    def test_english_case_insensitive(self):
        result_lower = parse_natural_date("today", reference_date=self.ref)
        result_upper = parse_natural_date("TODAY", reference_date=self.ref)
        assert result_lower.start_date == result_upper.start_date

    def test_tomorrow_case_insensitive(self):
        result = parse_natural_date("TOMORROW", reference_date=self.ref)
        assert result.start_date == self.ref + timedelta(days=1)

    # ── Additional edge cases ────────────────────────────────────────

    def test_zero_offset(self):
        """+0 or 0 should return same day."""
        result = parse_natural_date("+0", reference_date=self.ref)
        assert result.start_date == self.ref

    def test_original_preserved_in_result(self):
        result = parse_natural_date("明天", reference_date=self.ref)
        assert result.original == "明天"

    def test_this_week_english(self):
        result = parse_natural_date("this week", reference_date=self.ref)
        assert result.is_range

    def test_next_week_english(self):
        result = parse_natural_date("next week", reference_date=self.ref)
        assert result.is_range


class TestGenerateLabel:
    """Tests for _generate_label helper function."""

    def test_label_today(self):
        ref = date(2026, 6, 4)  # Thursday
        d = ref
        assert _generate_label(d, ref) == "今天 (周四)"

    def test_label_tomorrow(self):
        ref = date(2026, 6, 4)
        d = ref + timedelta(days=1)
        assert _generate_label(d, ref) == "明天 (周五)"

    def test_label_day_after_tomorrow(self):
        ref = date(2026, 6, 4)
        d = ref + timedelta(days=2)
        assert _generate_label(d, ref) == "后天 (周六)"

    def test_label_yesterday(self):
        ref = date(2026, 6, 4)
        d = ref - timedelta(days=1)
        assert _generate_label(d, ref) == "昨天 (周三)"

    def test_label_day_before_yesterday(self):
        ref = date(2026, 6, 4)
        d = ref - timedelta(days=2)
        assert _generate_label(d, ref) == "前天 (周二)"

    def test_label_far_future(self):
        ref = date(2026, 6, 4)
        d = date(2026, 12, 25)
        label = _generate_label(d, ref)
        assert "2026-12-25" in label
        assert "周五" in label
