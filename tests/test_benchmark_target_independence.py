from __future__ import annotations

from datetime import date, timedelta

from engierun.predictor_benchmark import select_cases


def _history(athlete, start, values):
    return [
        {"athlete_id": athlete, "event": "1500 Metres", "date": start + timedelta(days=i * 10), "seconds": value}
        for i, value in enumerate(values)
    ]


def test_case_identity_does_not_depend_on_target_mark_validity():
    rows = _history("a", date(2022, 1, 1), [250, 249, 248, 247, 246])
    changed = [dict(row) for row in rows]
    changed[-1]["seconds"] = "DNF"
    expected = select_cases(rows, count=1, start_date=date(2022, 2, 1))
    actual = select_cases(changed, count=1, start_date=date(2022, 2, 1))
    assert actual == expected
