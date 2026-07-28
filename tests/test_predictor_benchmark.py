from __future__ import annotations

from datetime import date, timedelta

from engierun.predictor_benchmark import evaluate_cases, select_cases


def _history(athlete, start, values, event="1500 Metres"):
    return [
        {
            "athlete_id": athlete,
            "event": event,
            "date": start + timedelta(days=i * 10),
            "seconds": seconds,
            "meet": "",
        }
        for i, seconds in enumerate(values)
    ]


def test_case_selection_never_looks_at_target_performance_values():
    rows = []
    start = date(2022, 1, 1)
    for i in range(12):
        rows += _history(f"a{i}", start + timedelta(days=i), [250, 249, 248, 247, 246, 245])
    changed = [dict(row) for row in rows]
    for row in changed:
        if row["date"] >= date(2022, 2, 10):
            row["seconds"] *= 1.5

    first = select_cases(rows, count=10, start_date=date(2022, 2, 1))
    second = select_cases(changed, count=10, start_date=date(2022, 2, 1))

    assert first == second
    assert all("actual_seconds" not in case for case in first)


def test_case_selection_is_time_ordered_and_caps_each_athlete_at_two():
    rows = []
    for athlete in ("a", "b", "c", "d", "e"):
        rows += _history(athlete, date(2022, 1, 1), range(250, 240, -1))
    cases = select_cases(rows, count=10, start_date=date(2022, 2, 1))
    assert [case["target_date"] for case in cases] == sorted(case["target_date"] for case in cases)
    assert max(sum(case["athlete_id"] == athlete for case in cases) for athlete in "abcde") <= 2


def test_case_selection_can_require_stable_recent_history_without_using_target_value():
    rows = _history("stable", date(2022, 1, 1), [250, 250, 250, 250, 249])
    rows += _history("variable", date(2022, 1, 1), [200, 300, 200, 300, 250])
    cases = select_cases(
        rows,
        count=1,
        start_date=date(2022, 2, 1),
        max_prior_cv=0.01,
    )
    assert cases[0]["athlete_id"] == "stable"


def test_evaluation_reports_each_case_baselines_metrics_and_leakage_checks():
    rows = []
    for i in range(10):
        rows += _history(f"a{i}", date(2020, 1, 1), [250, 249, 248, 247, 246, 245])
    cases = select_cases(rows, count=5, start_date=date(2020, 2, 1))
    report = evaluate_cases(rows, cases, threshold_percent=0.85)

    assert len(report["cases"]) == 5
    assert report["benchmark_label"] == "next recorded top-list performance"
    assert report["metrics"]["count"] == 5
    assert set(report["baselines"]) == {"last", "mean_last_four", "median_last_four", "recency_weighted"}
    assert report["leakage_checks"]["all_evidence_strictly_before_cutoff"] is True
    assert report["leakage_checks"]["all_comparable_targets_strictly_before_cutoff"] is True
    assert all("actual_seconds" in case and "absolute_percentage_error" in case for case in report["cases"])
