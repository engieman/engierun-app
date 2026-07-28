import csv
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from engierun import ivy_csv
from engierun.ivy_csv import (
    CANONICAL_COLUMNS,
    IVY_GENDERS,
    IVY_SCHOOLS,
    AuthorizationRequiredError,
    IdentityConflictError,
    QualityGateError,
    compile_authorized_csv,
    write_authorized_csv_dataset,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row(**changes: str) -> dict[str, str]:
    row = {
        "schema_version": "1",
        "athlete_id": "",
        "tfrrs_id": "100",
        "name": "Runner One",
        "school": "Dartmouth",
        "gender": "Male",
        "year": "SO-2",
        "profile_url": "https://www.tfrrs.org/athletes/100/Dartmouth/Runner_One.html",
        "record_type": "result",
        "date": "2026-01-02",
        "meet": "Authorized Meet",
        "event": "Mile",
        "mark": "4:10.00",
        "seconds": "250.0",
        "status": "",
        "source_url": "https://www.tfrrs.org/results/9000/Authorized_Meet.html",
    }
    row.update(changes)
    return row


def test_authorization_is_required_before_reading_csv(tmp_path):
    source = _write_csv(tmp_path / "source.csv", [_row()])

    with pytest.raises(AuthorizationRequiredError):
        compile_authorized_csv([source], authorized=False)


def test_compiles_bests_results_statuses_and_manual_ids_deterministically(tmp_path):
    source = _write_csv(
        tmp_path / "source.csv",
        [
            _row(record_type="result", date="2026-02-02", meet="Later", mark="DNF", seconds="", status="DNF"),
            _row(record_type="best", date="", meet="", event="Mile", mark="4:09.00", seconds="249"),
            _row(record_type="result", date="2026-01-02", meet="Earlier"),
            _row(
                athlete_id="manual:ivy:runner-two",
                tfrrs_id="",
                name="Runner Two",
                profile_url="",
                record_type="best",
                date="",
                meet="",
                event="PV",
                mark="4.75m",
                seconds="",
                source_url="",
            ),
        ],
    )

    dataset, report = compile_authorized_csv([source], authorized=True)

    assert [athlete["id"] for athlete in dataset["athletes"]] == [
        "manual:ivy:runner-two",
        "100",
    ]
    manual, runner = dataset["athletes"]
    assert manual["bests"]["PV"] == {"mark": "4.75m", "seconds": None}
    assert [result["date"] for result in runner["results"]] == ["2026-01-02", "2026-02-02"]
    assert runner["results"][1]["status"] == "DNF"
    assert runner["bests"]["Mile"]["seconds"] == 249.0
    assert report["accepted_rows"] == 4
    assert report["coverage"]["Dartmouth"]["Male"] == {"athletes": 2, "rows": 4}


def test_reports_identical_duplicates_missing_and_invalid_rows(tmp_path):
    valid = _row()
    source = _write_csv(
        tmp_path / "source.csv",
        [
            valid,
            dict(valid),
            _row(tfrrs_id="101", name="", profile_url="https://www.tfrrs.org/athletes/101/Dartmouth/Missing.html"),
            _row(tfrrs_id="102", profile_url="https://evil.example/athletes/102/X/Y.html"),
        ],
    )

    dataset, report = compile_authorized_csv([source], authorized=True)

    assert len(dataset["athletes"]) == 1
    assert report["input_rows"] == 4
    assert report["accepted_rows"] == 1
    assert report["duplicate_rows"] == 1
    assert report["missing_rows"] == 1
    assert report["invalid_rows"] == 1
    assert [issue["row"] for issue in report["issues"]] == [4, 5]


def test_rejects_conflicting_identity_for_same_tfrrs_id(tmp_path):
    source = _write_csv(
        tmp_path / "source.csv",
        [_row(), _row(name="Different Person", date="2026-02-03")],
    )

    with pytest.raises(IdentityConflictError, match="100"):
        compile_authorized_csv([source], authorized=True)


def test_rejects_profile_id_mismatch_and_bad_result_semantics(tmp_path):
    source = _write_csv(
        tmp_path / "source.csv",
        [
            _row(profile_url="https://www.tfrrs.org/athletes/999/Dartmouth/Runner_One.html"),
            _row(tfrrs_id="200", profile_url="https://www.tfrrs.org/athletes/200/Dartmouth/X.html", seconds="NaN"),
            _row(tfrrs_id="300", profile_url="https://www.tfrrs.org/athletes/300/Dartmouth/X.html", status="DNF", mark="DNF", seconds="250"),
        ],
    )

    dataset, report = compile_authorized_csv([source], authorized=True)

    assert dataset["athletes"] == []
    assert report["invalid_rows"] == 3


def test_compiler_never_needs_network_access(tmp_path, monkeypatch):
    source = _write_csv(tmp_path / "source.csv", [_row()])

    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    dataset, _ = compile_authorized_csv([source], authorized=True)
    assert dataset["athletes"][0]["name"] == "Runner One"


def test_atomic_writer_leaves_outputs_unchanged_on_conflict(tmp_path):
    source = _write_csv(tmp_path / "source.csv", [_row(), _row(name="Conflict")])
    output = tmp_path / "athletes.json"
    quality = tmp_path / "quality.json"
    output.write_text("old dataset\n", encoding="utf-8")
    quality.write_text("old report\n", encoding="utf-8")

    with pytest.raises(IdentityConflictError):
        write_authorized_csv_dataset(
            [source], output, quality, authorized=True
        )

    assert output.read_text(encoding="utf-8") == "old dataset\n"
    assert quality.read_text(encoding="utf-8") == "old report\n"


def test_atomic_writer_publishes_dataset_and_quality(tmp_path):
    source = _write_csv(tmp_path / "source.csv", [_row()])
    output = tmp_path / "generated" / "athletes.json"
    quality = tmp_path / "generated" / "quality.json"

    dataset, report = write_authorized_csv_dataset(
        [source], output, quality, authorized=True, allow_partial_ivy=True
    )

    assert json.loads(output.read_text(encoding="utf-8")) == dataset
    assert json.loads(quality.read_text(encoding="utf-8")) == report
    assert not list(output.parent.glob(".*.tmp"))


def test_writer_requires_all_eight_schools_and_both_genders_by_default(tmp_path):
    partial = _write_csv(tmp_path / "partial.csv", [_row()])
    with pytest.raises(QualityGateError, match="all-Ivy completeness"):
        write_authorized_csv_dataset(
            [partial],
            tmp_path / "partial.json",
            tmp_path / "partial-quality.json",
            authorized=True,
        )

    rows = []
    athlete_number = 1000
    for school in IVY_SCHOOLS:
        for gender in IVY_GENDERS:
            athlete_number += 1
            rows.append(
                _row(
                    tfrrs_id=str(athlete_number),
                    name=f"{school} {gender} Runner",
                    school=school,
                    gender=gender,
                    profile_url=(
                        f"https://www.tfrrs.org/athletes/{athlete_number}/"
                        f"{school}/{school}_{gender}.html"
                    ),
                )
            )
    complete = _write_csv(tmp_path / "complete.csv", rows)
    _, report = write_authorized_csv_dataset(
        [complete],
        tmp_path / "complete.json",
        tmp_path / "complete-quality.json",
        authorized=True,
    )

    assert report["ivy_complete"] is True
    assert report["missing_ivy_programs"] == []
    assert report["quality_passed"] is True


def test_timed_mark_and_seconds_must_describe_same_performance(tmp_path):
    source = _write_csv(
        tmp_path / "mismatch.csv",
        [_row(mark="8:20.00", seconds="1000")],
    )

    dataset, report = compile_authorized_csv([source], authorized=True)

    assert dataset["athletes"] == []
    assert report["invalid_rows"] == 1
    assert "different performances" in report["issues"][0]["detail"]


def test_atomic_writer_rolls_back_if_second_replace_fails(tmp_path, monkeypatch):
    source = _write_csv(tmp_path / "source.csv", [_row()])
    output = tmp_path / "athletes.json"
    quality = tmp_path / "quality.json"
    output.write_text("old dataset\n", encoding="utf-8")
    quality.write_text("old report\n", encoding="utf-8")
    real_replace = ivy_csv.os.replace
    calls = 0

    def fail_second(source_path, destination_path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(ivy_csv.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        write_authorized_csv_dataset(
            [source], output, quality, authorized=True, allow_partial_ivy=True
        )

    assert output.read_text(encoding="utf-8") == "old dataset\n"
    assert quality.read_text(encoding="utf-8") == "old report\n"


def test_local_cli_requires_explicit_authorization_attestation(tmp_path):
    source = _write_csv(tmp_path / "source.csv", [_row()])
    output = tmp_path / "athletes.json"
    quality = tmp_path / "quality.json"
    script = Path(__file__).parents[1] / "scripts" / "compile_authorized_ivy_csv.py"
    command = [
        sys.executable,
        str(script),
        "--input",
        str(source),
        "--output",
        str(output),
        "--quality-output",
        str(quality),
    ]

    denied = subprocess.run(command, text=True, capture_output=True, check=False)
    assert denied.returncode == 2
    assert not output.exists()

    allowed = subprocess.run(
        [*command, "--confirm-authorized-source", "--allow-partial-ivy"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert allowed.returncode == 0, allowed.stderr
    assert output.exists() and quality.exists()
