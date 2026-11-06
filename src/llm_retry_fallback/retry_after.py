"""RFC 9110 section 10.2.3 ``Retry-After`` parsing."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from llm_retry_fallback.errors import invalid_policy

__all__ = ["parse_retry_after"]

MAX_VALUE_LENGTH = 64

_MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MONTHS = {name: number for number, name in enumerate(_MONTH_NAMES, start=1)}
_MON = "|".join(_MONTH_NAMES)
_SHORT = "Mon|Tue|Wed|Thu|Fri|Sat|Sun"
_LONG = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
_D2 = "[0-9][0-9]"
_D4 = _D2 + _D2
_TIME = f"({_D2}):({_D2}):({_D2})"

# The three formats of RFC 9110 section 5.6.7. HTTP-date is case sensitive.
_IMF = re.compile(f"(?:{_SHORT}), ({_D2}) ({_MON}) ({_D4}) {_TIME} GMT")
_RFC850 = re.compile(f"(?:{_LONG}), ({_D2})-({_MON})-({_D2}) {_TIME} GMT")
_ASCTIME = re.compile(f"(?:{_SHORT}) ({_MON}) ( [0-9]|{_D2}) {_TIME} ({_D4})")


def _build(year: int, month: int, day: int, clock: tuple[int, int, int]) -> datetime | None:
    try:
        return datetime(year, month, day, *clock, tzinfo=timezone.utc)
    except ValueError:
        return None


def _resolve_two_digit_year(
    yy: int,
    month: int,
    day: int,
    clock: tuple[int, int, int],
    now: datetime,
) -> int:
    """Apply RFC 9110: more than 50 years ahead means the latest past year with these digits."""
    year = now.year - now.year % 100 + yy
    limit = (now.year + 50, now.month, now.day, now.hour, now.minute, now.second)
    candidate = (year, month, day, *clock)
    return year - 100 if candidate > limit else year


def _parse_http_date(text: str, now: datetime) -> datetime | None:
    if found := _IMF.fullmatch(text):
        day, month, year, hh, mm, ss = found.groups()
        return _build(int(year), _MONTHS[month], int(day), (int(hh), int(mm), int(ss)))
    if found := _RFC850.fullmatch(text):
        day, month, yy, hh, mm, ss = found.groups()
        clock = (int(hh), int(mm), int(ss))
        resolved = _resolve_two_digit_year(int(yy), _MONTHS[month], int(day), clock, now)
        return _build(resolved, _MONTHS[month], int(day), clock)
    if found := _ASCTIME.fullmatch(text):
        month, day, hh, mm, ss, year = found.groups()
        return _build(int(year), _MONTHS[month], int(day), (int(hh), int(mm), int(ss)))
    return None


def parse_retry_after(value: str, now: datetime) -> float | None:
    """Parse a ``Retry-After`` header value into seconds to wait.

    Accepts RFC 9110 ``delay-seconds`` (ASCII digits only) or an HTTP-date in IMF-fixdate,
    rfc850-date or asctime-date format. Surrounding spaces and tabs are trimmed. Dates in the
    past give ``0.0``. Values longer than 64 characters or in any other form give ``None``.

    Args:
        value: The raw header value.
        now: The current time; must be timezone-aware.

    Returns:
        Seconds to wait, or ``None`` if the value is not a valid ``Retry-After``.

    Raises:
        FallbackError: with code ``invalid_policy`` when ``now`` is naive.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise invalid_policy("now must be a timezone-aware datetime")
    if not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH:
        return None
    text = value.strip(" \t")
    if text.isascii() and text.isdigit():
        return float(int(text))
    now_utc = now.astimezone(timezone.utc)
    moment = _parse_http_date(text, now_utc)
    if moment is None:
        return None
    return max(0.0, (moment - now_utc).total_seconds())
