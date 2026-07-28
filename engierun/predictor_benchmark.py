"""Deterministic, leakage-auditable benchmark helpers for the predictor."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from .predictor import predict_next_performance


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def select_cases(
    records: Sequence[Mapping[str, Any]],
    *,
    count: int,
    start_date: date,
    end_date: date | None = None,
    seed: str = "engierun-next-top-list-v1",
    max_per_athlete: int = 2,
    max_prior_cv: float | None = None,
) -> list[dict[str, str]]:
    """Fix case identities using metadata only, never target performance values.

    Cases need four earlier dates in the same event. Ambiguous same-day targets
    are excluded. A stable hash samples eligible identities; the returned sample
    is then chronological for a time-ordered report.
    """
    grouped: dict[tuple[str, str], list[tuple[date, float | None]]] = defaultdict(list)
    for row in records:
        if "athlete_id" not in row or "event" not in row or "date" not in row:
            continue
        seconds = row.get("seconds")
        valid_seconds = (
            float(seconds)
            if isinstance(seconds, (int, float))
            and not isinstance(seconds, bool)
            and math.isfinite(float(seconds))
            and float(seconds) > 0
            else None
        )
        grouped[(str(row["athlete_id"]), str(row["event"]))].append(
            (_date(row["date"]), valid_seconds)
        )

    eligible: list[dict[str, str]] = []
    for (athlete_id, event), observations in grouped.items():
        days = [day for day, _ in observations]
        counts = Counter(days)
        unique_days = sorted(counts)
        sorted_observations = sorted(observations, key=lambda item: item[0])
        for target_day in unique_days:
            if counts[target_day] != 1:
                continue
            if target_day < start_date or (end_date is not None and target_day >= end_date):
                continue
            prior_values = [
                seconds
                for day, seconds in sorted_observations
                if day < target_day and seconds is not None
            ][-4:]
            if len(prior_values) < 4:
                continue
            if max_prior_cv is not None:
                mean = statistics.fmean(prior_values)
                if statistics.pstdev(prior_values) / mean > max_prior_cv:
                    continue
            eligible.append(
                {
                    "athlete_id": athlete_id,
                    "event": event,
                    "target_date": target_day.isoformat(),
                }
            )

    def sample_key(case: Mapping[str, str]) -> str:
        identity = "|".join((seed, case["athlete_id"], case["event"], case["target_date"]))
        return hashlib.sha256(identity.encode()).hexdigest()

    selected = []
    athlete_counts: Counter[str] = Counter()
    for case in sorted(eligible, key=lambda item: (sample_key(item), item["target_date"])):
        if athlete_counts[case["athlete_id"]] >= max_per_athlete:
            continue
        selected.append(case)
        athlete_counts[case["athlete_id"]] += 1
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError(f"requested {count} cases but only {len(selected)} satisfy the protocol")
    return sorted(selected, key=lambda item: (item["target_date"], item["athlete_id"], item["event"]))


def _metrics(errors_seconds: Sequence[float], errors_percent: Sequence[float], threshold: float) -> dict[str, Any]:
    return {
        "count": len(errors_percent),
        "hits": sum(error <= threshold for error in errors_percent),
        "hit_rate_percent": round(sum(error <= threshold for error in errors_percent) / len(errors_percent) * 100, 2),
        "mae_seconds": round(statistics.fmean(errors_seconds), 4),
        "mape_percent": round(statistics.fmean(errors_percent), 4),
    }


def evaluate_cases(
    records: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, str]],
    *,
    threshold_percent: float = 0.85,
    neighbor_count: int = 12,
    neighbor_blend: float = 0.2,
) -> dict[str, Any]:
    """Evaluate already-fixed cases, including four transparent baselines."""
    targets: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in records:
        key = (str(row.get("athlete_id")), str(row.get("event")), _date(row.get("date")).isoformat())
        targets[key] = row

    baseline_names = ("last", "mean_last_four", "median_last_four", "recency_weighted")
    baseline_errors: dict[str, tuple[list[float], list[float]]] = {
        name: ([], []) for name in baseline_names
    }
    candidate_abs: list[float] = []
    candidate_pct: list[float] = []
    output_cases = []
    all_evidence_prior = True
    all_comparables_prior = True

    for case in cases:
        key = (case["athlete_id"], case["event"], case["target_date"])
        target = targets[key]
        actual = float(target["seconds"])
        cutoff = date.fromisoformat(case["target_date"])
        prediction = predict_next_performance(
            records,
            athlete_id=case["athlete_id"],
            event=case["event"],
            cutoff=cutoff,
            neighbor_count=neighbor_count,
            neighbor_blend=neighbor_blend,
        )
        predicted = float(prediction["predicted_seconds"])
        abs_error = abs(predicted - actual)
        pct_error = abs_error / actual * 100
        candidate_abs.append(abs_error)
        candidate_pct.append(pct_error)

        prior = sorted(
            (
                (_date(row["date"]), float(row["seconds"]))
                for row in records
                if str(row.get("athlete_id")) == case["athlete_id"]
                and str(row.get("event")) == case["event"]
                and _date(row["date"]) < cutoff
                and isinstance(row.get("seconds"), (int, float))
                and not isinstance(row.get("seconds"), bool)
                and math.isfinite(float(row["seconds"]))
                and float(row["seconds"]) > 0
            ),
            key=lambda item: item[0],
        )
        values = [seconds for _, seconds in prior[-4:]]
        baseline_predictions = {
            "last": values[-1],
            "mean_last_four": statistics.fmean(values),
            "median_last_four": statistics.median(values),
            "recency_weighted": sum((i + 1) * value for i, value in enumerate(values)) / 10,
        }
        for name, value in baseline_predictions.items():
            absolute = abs(value - actual)
            baseline_errors[name][0].append(absolute)
            baseline_errors[name][1].append(absolute / actual * 100)

        all_evidence_prior &= prediction["latest_evidence_date"] < case["target_date"]
        all_comparables_prior &= all(
            episode["target_date"] < case["target_date"]
            for episode in prediction["comparable_episodes"]
        )
        output_cases.append(
            {
                **dict(case),
                "predicted_seconds": round(predicted, 4),
                "actual_seconds": round(actual, 4),
                "absolute_error_seconds": round(abs_error, 4),
                "absolute_percentage_error": round(pct_error, 4),
                "hit": pct_error <= threshold_percent,
                "uncertainty_seconds": prediction["uncertainty_seconds"],
                "confidence": prediction["confidence"],
                "confidence_kind": prediction["confidence_kind"],
                "uncertainty_kind": prediction["uncertainty_kind"],
                "recent_history": prediction["recent_history"],
                "comparable_episodes": prediction["comparable_episodes"],
                "baseline_predictions": {name: round(value, 4) for name, value in baseline_predictions.items()},
            }
        )

    return {
        "benchmark_label": "next recorded top-list performance",
        "benchmark_caveat": "The source contains ranked/top-list marks, not complete race histories; targets are not necessarily the athlete's genuine next race.",
        "threshold_percent": threshold_percent,
        "metrics": _metrics(candidate_abs, candidate_pct, threshold_percent),
        "baselines": {
            name: _metrics(errors[0], errors[1], threshold_percent)
            for name, errors in baseline_errors.items()
        },
        "leakage_checks": {
            "all_evidence_strictly_before_cutoff": all_evidence_prior,
            "all_comparable_targets_strictly_before_cutoff": all_comparables_prior,
            "selection_uses_target_performance_values": False,
        },
        "cases": output_cases,
    }
