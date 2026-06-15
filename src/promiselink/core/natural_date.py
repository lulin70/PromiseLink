"""Natural language date parser for Chinese + English date expressions."""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class NaturalDateResult:
    """Result of parsing a natural language date expression."""

    start_date: date
    end_date: date  # Same as start_date for single-day queries
    label: str  # Human-readable label e.g., "今天 (周四)"
    is_range: bool  # Whether this represents a date range
    original: str  # Original input


# Chinese keyword mappings
_CN_DATE_KEYWORDS = {
    "今天": 0,
    "今日": 0,
    "today": 0,
    "t": 0,
    "明天": 1,
    "明日": 1,
    "tomorrow": 1,
    "tmr": 1,
    "后天": 2,
    "后日": 2,
    "day after tomorrow": 2,
    "昨天": -1,
    "昨日": -1,
    "yesterday": -1,
    "yst": -1,
}

_CN_WEEK_KEYWORDS = {
    "本周": 0,
    "这周": 0,
    "this week": 0,
    "下周": 1,
    "next week": 1,
    "上周": -1,
    "last week": -1,
}

# Weekday name mapping for label generation
_WEEKDAY_NAMES_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def parse_natural_date(
    text: str | None, reference_date: date | None = None
) -> NaturalDateResult:
    """Parse natural language date expression into concrete date(s).

    Args:
        text: Natural language date string (or None for today)
        reference_date: Reference date for relative calculations (defaults to today)

    Returns:
        NaturalDateResult with start_date, end_date, label, etc.

    Raises:
        ValueError: If text cannot be parsed as any recognized format
    """
    ref = reference_date or date.today()
    original = (text or "").strip()

    if not original:
        result = _build_single_day(ref, ref, original or "(default)")
        result.label = f"今天 ({_WEEKDAY_NAMES_CN[ref.weekday()]})"
        return result

    normalized = original.strip().lower()

    # Try ISO format first: YYYY-MM-DD
    iso_result = _parse_iso_date(normalized, ref)
    if iso_result is not None:
        return iso_result

    # Try Chinese/English day keywords
    keyword_result = _parse_day_keyword(normalized, ref)
    if keyword_result is not None:
        return keyword_result

    # Try relative expressions like '3天后', '+3', '-5', '3d'
    relative_result = _parse_relative_days(normalized, ref)
    if relative_result is not None:
        return relative_result

    # Try week expressions like '本周', '下周'
    week_result = _parse_week_expression(normalized, ref)
    if week_result is not None:
        return week_result

    raise ValueError(f"无法解析日期表达式: '{original}'")


def _parse_iso_date(text: str, ref: date) -> NaturalDateResult | None:
    """Parse ISO format date: YYYY-MM-DD."""
    iso_pattern = r"^(\d{4})-(\d{2})-(\d{2})$"
    match = re.match(iso_pattern, text)
    if match is None:
        return None
    try:
        d = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        raise ValueError(f"无效的日期格式: '{text}'")
    return _build_single_day(d, ref, text)


def _parse_day_keyword(text: str, ref: date) -> NaturalDateResult | None:
    """Parse Chinese/English day keywords like '今天', 'tomorrow'."""
    for keyword, offset in _CN_DATE_KEYWORDS.items():
        if text == keyword:
            target = ref + timedelta(days=offset)
            return _build_single_day(target, ref, text)
    return None


def _parse_relative_days(text: str, ref: date) -> NaturalDateResult | None:
    """Parse relative expressions like '3天后', '+3', '-5', '3d'."""
    # Pattern 1: N天[后|前] — Chinese relative with direction suffix
    cn_pattern = r"^([+-]?\d+)\s*天([后前])$"
    match = re.match(cn_pattern, text)
    if match is not None:
        offset = int(match.group(1))
        direction = match.group(2)
        if direction == "前":
            offset = -abs(offset)
        else:  # 后
            offset = abs(offset)
        target = ref + timedelta(days=offset)
        return _build_single_day(target, ref, text)

    # Pattern 2: (+|-)N or Nd or N days
    patterns = [
        r"^([+-]\d+)$",  # +3, -5
        r"^(\d+)d$",  # 3d
        r"^([+-]?\d+)\s*days?$",  # 3 days, +2 days
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match is not None:
            offset = int(match.group(1))
            target = ref + timedelta(days=offset)
            return _build_single_day(target, ref, text)
    return None


def _parse_week_expression(text: str, ref: date) -> NaturalDateResult | None:
    """Parse week expressions like '本周', '下周'."""
    for keyword, offset in _CN_WEEK_KEYWORDS.items():
        if text == keyword:
            today_weekday = ref.weekday()  # Monday=0, Sunday=6
            # Calculate Monday of the target week
            monday = ref - timedelta(days=today_weekday) + timedelta(weeks=offset)
            sunday = monday + timedelta(days=6)
            weekday_name = _WEEKDAY_NAMES_CN[today_weekday]
            if offset == 0:
                label = f"本周 ({monday.strftime('%m/%d')} ~ {sunday.strftime('%m/%d')})"
            elif offset > 0:
                label = f"下周 ({monday.strftime('%m/%d')} ~ {sunday.strftime('%m/%d')})"
            else:
                label = f"上周 ({monday.strftime('%m/%d')} ~ {sunday.strftime('%m/%d')})"
            return NaturalDateResult(
                start_date=monday,
                end_date=sunday,
                label=label,
                is_range=True,
                original=text,
            )
    return None


def _build_single_day(target: date, ref: date, original: str) -> NaturalDateResult:
    """Build a NaturalDateResult for a single day."""
    return NaturalDateResult(
        start_date=target,
        end_date=target,
        label=_generate_label(target, ref),
        is_range=False,
        original=original,
    )


def _generate_label(d: date, ref: date) -> str:
    """Generate human-readable label like '今天 (周四)' or '明天 (周五)'."""
    diff = (d - ref).days
    weekday = _WEEKDAY_NAMES_CN[d.weekday()]
    if diff == 0:
        return f"今天 ({weekday})"
    elif diff == 1:
        return f"明天 ({weekday})"
    elif diff == 2:
        return f"后天 ({weekday})"
    elif diff == -1:
        return f"昨天 ({weekday})"
    elif diff == -2:
        return f"前天 ({weekday})"
    else:
        return d.strftime("%Y-%m-%d") + f" ({weekday})"
