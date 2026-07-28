"""Fast, explainable, leakage-safe next-performance prediction.

The predictor accepts generic result mappings and deliberately knows nothing about
any results provider.  A prediction cutoff is exclusive: records and comparable
episode outcomes on or after it cannot influence the result.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from heapq import nsmallest
from numbers import Real
from typing import Any


class InsufficientHistoryError(ValueError):
    """Raised when fewer than four prior same-event performances are available."""


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError(f"invalid result date: {value!r}")


def _valid_seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    seconds = float(value)
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _baseline(history: Sequence[tuple[date, float]]) -> float:
    recent = history[-4:]
    # Newer results receive more weight while a median component limits outliers.
    weighted = sum((i + 1) * seconds for i, (_, seconds) in enumerate(recent)) / 10
    return 0.6 * weighted + 0.4 * statistics.median(seconds for _, seconds in recent)


def _features(history: Sequence[tuple[date, float]], target_date: date) -> tuple[float, ...]:
    recent = history[-4:]
    values = [seconds for _, seconds in recent]
    baseline = _baseline(history)
    mean = statistics.fmean(values)
    dispersion = statistics.pstdev(values) / mean if mean else 0.0
    # Least-squares slope over observations, expressed relative to current level.
    slope = sum((i - 1.5) * value for i, value in enumerate(values)) / 5
    trend = slope / baseline
    gap = (target_date - recent[-1][0]).days
    # Cyclic season features avoid a discontinuity between December and January.
    angle = 2 * math.pi * target_date.timetuple().tm_yday / 365.25
    return (dispersion, trend, min(max(gap, 0), 365) / 90, math.sin(angle), math.cos(angle))


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    scales = (0.025, 0.02, 1.0, 1.0, 1.0)
    return math.sqrt(sum(((a - b) / scale) ** 2 for a, b, scale in zip(left, right, scales)))


def _normalise_records(records: Sequence[Mapping[str, Any]], event: str) -> list[dict[str, Any]]:
    normalised = []
    for row in records:
        if row.get("event") != event:
            continue
        seconds = _valid_seconds(row.get("seconds"))
        if seconds is None or "athlete_id" not in row:
            continue
        normalised.append(
            {
                "athlete_id": str(row["athlete_id"]),
                "date": _date(row.get("date")),
                "seconds": seconds,
                "meet": str(row.get("meet", "")),
            }
        )
    normalised.sort(key=lambda row: (row["athlete_id"], row["date"], row["seconds"]))
    return normalised


def _episodes(rows: Sequence[Mapping[str, Any]], cutoff: date) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["athlete_id"])].append(row)

    episodes = []
    for athlete_id, athlete_rows in grouped.items():
        # A same-day mark is not prior evidence for another same-day mark. Build
        # each day's episodes before adding that day's records to history.
        history: list[tuple[date, float]] = []
        by_day: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
        for row in athlete_rows:
            by_day[row["date"]].append(row)
        for target_date in sorted(by_day):
            if target_date >= cutoff:
                break
            if len(history) >= 4:
                features = _features(history, target_date)
                baseline = _baseline(history)
                for target in by_day[target_date]:
                    episodes.append(
                        {
                            "athlete_id": athlete_id,
                            "target_date": target_date,
                            "target_seconds": target["seconds"],
                            "baseline_seconds": baseline,
                            "ratio": target["seconds"] / baseline,
                            "features": features,
                        }
                    )
            history.extend((target_date, row["seconds"]) for row in by_day[target_date])
    return episodes


def predict_next_performance(
    records: Sequence[Mapping[str, Any]],
    *,
    athlete_id: str,
    event: str,
    cutoff: date | str,
    neighbor_count: int = 12,
    neighbor_blend: float = 0.2,
) -> dict[str, Any]:
    """Predict the next recorded same-event performance before an exclusive cutoff.

    ``records`` may contain all athletes so pre-cutoff comparable episodes can be
    discovered.  Returned evidence includes ISO dates, uncertainty, confidence,
    and the nearest episodes that informed the adjustment.
    """
    cutoff_date = _date(cutoff)
    rows = _normalise_records(records, event)
    own = [
        (row["date"], row["seconds"])
        for row in rows
        if row["athlete_id"] == str(athlete_id) and row["date"] < cutoff_date
    ]
    if len(own) < 4:
        raise InsufficientHistoryError(
            f"need four prior {event} performances before {cutoff_date.isoformat()}"
        )

    baseline = _baseline(own)
    own_features = _features(own, cutoff_date)
    episodes = _episodes(rows, cutoff_date)
    ranked = nsmallest(
        max(0, neighbor_count),
        ((max(_distance(own_features, episode["features"]), 1e-6), episode) for episode in episodes),
        key=lambda pair: (pair[0], pair[1]["target_date"], pair[1]["athlete_id"]),
    )

    if ranked:
        weights = [1 / (0.15 + distance) for distance, _ in ranked]
        neighbor_ratio = sum(weight * episode["ratio"] for weight, (_, episode) in zip(weights, ranked)) / sum(weights)
        adjustment = neighbor_blend * (neighbor_ratio - 1)
        predicted = baseline * (1 + adjustment)
        residuals = sorted(abs(episode["ratio"] - neighbor_ratio) for _, episode in ranked)
        uncertainty_ratio = residuals[min(len(residuals) - 1, math.floor(0.8 * len(residuals)))]
        closeness = 1 / (1 + statistics.fmean(distance for distance, _ in ranked))
        confidence = min(0.95, 0.35 + 0.35 * min(len(ranked) / 12, 1) + 0.3 * closeness)
    else:
        neighbor_ratio = 1.0
        adjustment = 0.0
        predicted = baseline
        uncertainty_ratio = max(statistics.pstdev(value for _, value in own[-4:]) / baseline, 0.01)
        confidence = min(0.6, 0.25 + 0.08 * len(own))

    uncertainty_ratio = max(uncertainty_ratio, 0.005)
    comparable = [
        {
            "athlete_id": episode["athlete_id"],
            "target_date": episode["target_date"].isoformat(),
            "baseline_seconds": round(episode["baseline_seconds"], 4),
            "next_seconds": round(episode["target_seconds"], 4),
            "change_percent": round((episode["ratio"] - 1) * 100, 4),
            "distance": round(distance, 5),
        }
        for distance, episode in ranked
    ]
    recent = [
        {"date": day.isoformat(), "seconds": seconds}
        for day, seconds in own[-4:]
    ]
    return {
        "athlete_id": str(athlete_id),
        "event": event,
        "cutoff": cutoff_date.isoformat(),
        "predicted_seconds": round(predicted, 4),
        "uncertainty_seconds": [
            round(predicted * (1 - uncertainty_ratio), 4),
            round(predicted * (1 + uncertainty_ratio), 4),
        ],
        "confidence": round(confidence, 4),
        "confidence_kind": "heuristic_neighbor_evidence_score",
        "uncertainty_kind": "uncalibrated_neighbor_residual_range",
        "recent_history": recent,
        "latest_evidence_date": own[-1][0].isoformat(),
        "comparable_episodes": comparable,
        "explanation": {
            "method": "robust recency baseline plus pre-cutoff comparable episodes",
            "baseline_seconds": round(baseline, 4),
            "neighbor_change_percent": round((neighbor_ratio - 1) * 100, 4),
            "neighbor_adjustment_percent": round(adjustment * 100, 4),
            "neighbor_count": len(ranked),
        },
    }
