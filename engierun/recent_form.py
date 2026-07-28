"""Pure recent-form comparison logic for one canonical event."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from numbers import Real
from typing import Any


def _result_date(result: Mapping[str, Any]) -> date | None:
    value = result.get("date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _is_valid_result(result: Mapping[str, Any], event: str) -> bool:
    """Return whether a result is a completed, positive timed mark for ``event``."""
    if result.get("event") != event or _result_date(result) is None:
        return False

    status = result.get("status")
    if status is not None and (
        not isinstance(status, str) or status.strip().upper() != "OK"
    ):
        return False

    seconds = result.get("seconds")
    if not isinstance(seconds, Real) or isinstance(seconds, bool):
        return False
    seconds_value = float(seconds)
    return math.isfinite(seconds_value) and seconds_value > 0


def _recent_results(
    results: Sequence[Mapping[str, Any]], event: str, limit: int
) -> list[Mapping[str, Any]]:
    """Select the newest valid results for an exact canonical event."""
    if limit <= 0:
        return []
    valid = [result for result in results if _is_valid_result(result, event)]
    valid.sort(key=lambda result: _result_date(result) or date.min, reverse=True)
    return valid[:limit]


def compare_recent_form(
    a_results: Sequence[Mapping[str, Any]],
    b_results: Sequence[Mapping[str, Any]],
    *,
    event: str,
    limit: int = 4,
) -> dict[str, Any]:
    """Compare two athletes by their average of recent valid same-event marks.

    Successful parser results use a null status, while normalized domain rows may
    use ``"OK"``. Other statuses and invalid times are excluded. When either
    athlete has no valid sample, comparison-only values are ``None``.
    """
    recent_a = _recent_results(a_results, event, limit)
    recent_b = _recent_results(b_results, event, limit)

    a_average = (
        sum(float(result["seconds"]) for result in recent_a) / len(recent_a)
        if recent_a
        else None
    )
    b_average = (
        sum(float(result["seconds"]) for result in recent_b) / len(recent_b)
        if recent_b
        else None
    )

    winner: str | None = None
    difference_seconds: float | None = None
    percent_faster: float | None = None
    if a_average is not None and b_average is not None:
        difference_seconds = abs(a_average - b_average)
        if a_average < b_average:
            winner = "a"
        elif b_average < a_average:
            winner = "b"
        else:
            winner = "tie"
        percent_faster = difference_seconds / max(a_average, b_average) * 100

    return {
        "event": event,
        "a_results": recent_a,
        "b_results": recent_b,
        "a_average_seconds": a_average,
        "b_average_seconds": b_average,
        "winner": winner,
        "difference_seconds": difference_seconds,
        "percent_faster": percent_faster,
        "a_sample_size": len(recent_a),
        "b_sample_size": len(recent_b),
    }
