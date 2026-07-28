"""Authorization-gated, local-only compiler for canonical Ivy result CSV files.

This module intentionally has no HTTP client and accepts filesystem paths only.  It
must not be used to discover or download TFRRS/FloSports data.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .tfrrs import is_timed_event, parse_timed_mark_seconds, validate_profile_url

SCHEMA_VERSION = 1
COMPILER_VERSION = "ivy-authorized-csv-v1"
IVY_SCHOOLS = (
    "Brown",
    "Columbia",
    "Cornell",
    "Dartmouth",
    "Harvard",
    "Penn",
    "Princeton",
    "Yale",
)
IVY_GENDERS = ("Female", "Male")
CANONICAL_COLUMNS = [
    "schema_version",
    "athlete_id",
    "tfrrs_id",
    "name",
    "school",
    "gender",
    "year",
    "profile_url",
    "record_type",
    "date",
    "meet",
    "event",
    "mark",
    "seconds",
    "status",
    "source_url",
]
_STATUS_MARKS = {"DNF", "DNS", "DQ", "FS", "NT", "NH", "NM", "FOUL"}
_SAFE_TFRRS_PATH = re.compile(
    r"/(?:athletes/\d+/[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+\.html|"
    r"results/\d+/[A-Za-z0-9._~/-]+\.html)"
)


class AuthorizationRequiredError(PermissionError):
    """Raised unless the caller attests that the local source is authorized."""


class IdentityConflictError(ValueError):
    """Raised when one stable athlete ID has contradictory identity fields."""


class QualityGateError(RuntimeError):
    """Raised when rejected source rows would otherwise be published."""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _validate_source_url(value: str) -> str:
    """Validate a canonical, exact TFRRS profile/result URL without opening it."""
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid source URL port") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"tfrrs.org", "www.tfrrs.org"}
        or parsed.hostname not in {"tfrrs.org", "www.tfrrs.org"}
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
        or "\\" in parsed.path
        or "//" in parsed.path
        or not _SAFE_TFRRS_PATH.fullmatch(parsed.path)
    ):
        raise ValueError("source_url must be an exact canonical HTTPS TFRRS profile/result URL")
    return value


def _profile_id(url: str) -> str:
    validate_profile_url(url)
    return urlparse(url).path.split("/")[2]


def _seconds(value: str) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError("seconds must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("seconds must be positive and finite")
    return parsed


def _validate_date(value: str) -> str:
    if not value:
        raise ValueError("result rows require date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("date must be ISO YYYY-MM-DD") from exc


def _read_rows(path: Path) -> tuple[list[tuple[int, dict[str, str]]], str]:
    if not path.is_file():
        raise FileNotFoundError(f"local CSV does not exist: {path}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV must be UTF-8: {path}") from exc
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError(f"CSV is missing a header: {path}")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError(f"CSV has duplicate headers: {path}")
    if reader.fieldnames != CANONICAL_COLUMNS:
        raise ValueError(
            f"CSV columns must exactly match canonical schema: {','.join(CANONICAL_COLUMNS)}"
        )
    rows: list[tuple[int, dict[str, str]]] = []
    for line_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"row {line_number} has extra columns")
        rows.append((line_number, {key: value or "" for key, value in row.items()}))
    return rows, hashlib.sha256(raw).hexdigest()


def _normalize_row(raw: dict[str, str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        key: _clean(raw.get(key, "")) for key in CANONICAL_COLUMNS
    }
    missing = [
        key
        for key in ("schema_version", "name", "school", "gender", "record_type", "event", "mark")
        if not row[key]
    ]
    if not row["tfrrs_id"] and not row["athlete_id"]:
        missing.append("tfrrs_id or athlete_id")
    if missing:
        raise KeyError(", ".join(missing))
    if row["schema_version"] != str(SCHEMA_VERSION):
        raise ValueError(f"unsupported schema_version {row['schema_version']!r}")
    if row["school"] not in IVY_SCHOOLS:
        raise ValueError("school must be one of the eight canonical Ivy programs")
    if row["gender"] not in IVY_GENDERS:
        raise ValueError("gender must be Female or Male")
    if row["tfrrs_id"] and not row["tfrrs_id"].isdigit():
        raise ValueError("tfrrs_id must contain digits only")
    if row["athlete_id"] and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._~-]{2,127}", row["athlete_id"]):
        raise ValueError("athlete_id is not a stable manual ID")

    stable_id = row["tfrrs_id"] or row["athlete_id"]
    if row["profile_url"]:
        profile_id = _profile_id(row["profile_url"])
        if not row["tfrrs_id"]:
            raise ValueError("profile_url requires tfrrs_id")
        if profile_id != row["tfrrs_id"]:
            raise ValueError("profile_url athlete ID does not match tfrrs_id")
    elif row["tfrrs_id"]:
        raise KeyError("profile_url")
    if row["source_url"]:
        _validate_source_url(row["source_url"])

    record_type = row["record_type"].lower()
    if record_type not in {"best", "result"}:
        raise ValueError("record_type must be best or result")
    seconds = _seconds(row["seconds"])
    status = row["status"].upper()
    if status and status not in _STATUS_MARKS:
        raise ValueError("unsupported status")
    if status and seconds is not None:
        raise ValueError("status rows cannot contain seconds")
    if status and row["mark"].upper() != status:
        raise ValueError("status must match mark")
    if not status and row["mark"].upper() in _STATUS_MARKS:
        raise ValueError("status mark requires status")
    if not status and is_timed_event(row["event"]):
        parsed_mark_seconds = parse_timed_mark_seconds(row["mark"], row["event"])
        if parsed_mark_seconds is None:
            raise ValueError("timed event mark must be a valid elapsed time")
        if seconds is not None and not math.isclose(
            seconds, parsed_mark_seconds, rel_tol=0.0, abs_tol=0.011
        ):
            raise ValueError("mark and seconds describe different performances")
        seconds = parsed_mark_seconds
    elif not status and seconds is not None:
        raise ValueError("non-timed marks cannot contain seconds")
    if record_type == "result":
        row["date"] = _validate_date(row["date"])
        if not row["meet"]:
            raise KeyError("meet")
    elif status:
        raise ValueError("best rows cannot contain a status")

    row.update(
        {
            "stable_id": stable_id,
            "record_type": record_type,
            "seconds_value": seconds,
            "status": status or None,
        }
    )
    return row


def _identity(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(row[key] for key in ("name", "school", "gender", "year", "profile_url", "tfrrs_id", "athlete_id"))


def compile_authorized_csv(
    input_paths: Iterable[str | Path], *, authorized: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile authorized local CSVs into the static UI athlete schema.

    ``authorized=True`` is an explicit caller attestation that every input is a
    licensed export, was supplied by its owner, or is otherwise covered by written
    permission. No input is read before this gate is checked.
    """
    if not authorized:
        raise AuthorizationRequiredError(
            "authorization attestation required for local athlete data"
        )
    paths = [Path(path) for path in input_paths]
    if not paths:
        raise ValueError("at least one local CSV path is required")

    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    input_rows = missing_rows = invalid_rows = 0
    for path in paths:
        rows, digest = _read_rows(path)
        inputs.append({"path": str(path), "sha256": digest, "rows": len(rows)})
        input_rows += len(rows)
        for line_number, raw in rows:
            try:
                normalized.append(_normalize_row(raw))
            except KeyError as exc:
                missing_rows += 1
                issues.append(
                    {"source": str(path), "row": line_number, "code": "missing", "detail": str(exc).strip("'")}
                )
            except ValueError as exc:
                invalid_rows += 1
                issues.append(
                    {"source": str(path), "row": line_number, "code": "invalid", "detail": str(exc)}
                )

    identities: dict[str, tuple[str, ...]] = {}
    for row in normalized:
        previous = identities.setdefault(row["stable_id"], _identity(row))
        if previous != _identity(row):
            raise IdentityConflictError(
                f"conflicting identity fields for athlete {row['stable_id']}"
            )

    unique_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicate_rows = 0
    for row in normalized:
        key = tuple(row[column] for column in CANONICAL_COLUMNS)
        if key in unique_rows:
            duplicate_rows += 1
        else:
            unique_rows[key] = row

    athlete_rows: dict[str, dict[str, Any]] = {}
    best_keys: dict[tuple[str, str], tuple[Any, ...]] = {}
    for row in sorted(
        unique_rows.values(),
        key=lambda item: (
            item["stable_id"], item["date"], item["meet"], item["event"],
            item["record_type"], item["mark"], item["source_url"],
        ),
    ):
        athlete = athlete_rows.setdefault(
            row["stable_id"],
            {
                "id": row["stable_id"],
                "name": row["name"],
                "school": row["school"],
                "gender": row["gender"],
                "year": row["year"] or None,
                "profile_url": row["profile_url"] or None,
                "bests": {},
                "results": [],
            },
        )
        mark = {"mark": row["mark"], "seconds": row["seconds_value"]}
        if row["source_url"]:
            mark["source_url"] = row["source_url"]
        if row["record_type"] == "best":
            best_key = (row["stable_id"], row["event"])
            signature = (row["mark"], row["seconds_value"], row["source_url"])
            previous = best_keys.setdefault(best_key, signature)
            if previous != signature:
                raise IdentityConflictError(
                    f"conflicting best rows for athlete {row['stable_id']} event {row['event']}"
                )
            athlete["bests"][row["event"]] = mark
        else:
            result = {
                "date": row["date"],
                "meet": row["meet"],
                "event": row["event"],
                "mark": row["mark"],
                "seconds": row["seconds_value"],
                "status": row["status"],
            }
            if row["source_url"]:
                result["source_url"] = row["source_url"]
            athlete["results"].append(result)

    athletes = [
        athlete_rows[key]
        for key in sorted(athlete_rows, key=lambda value: (not value.startswith("manual:"), value))
    ]
    coverage_acc: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"ids": set(), "rows": 0})
    )
    for row in unique_rows.values():
        bucket = coverage_acc[row["school"]][row["gender"]]
        bucket["ids"].add(row["stable_id"])
        bucket["rows"] += 1
    coverage = {
        school: {
            gender: {"athletes": len(values["ids"]), "rows": values["rows"]}
            for gender, values in sorted(genders.items())
        }
        for school, genders in sorted(coverage_acc.items())
    }
    accepted_rows = len(unique_rows)
    missing_ivy_programs = [
        {"school": school, "gender": gender}
        for school in IVY_SCHOOLS
        for gender in IVY_GENDERS
        if coverage.get(school, {}).get(gender, {}).get("athletes", 0) == 0
    ]
    ivy_complete = not missing_ivy_programs
    row_quality_passed = missing_rows == 0 and invalid_rows == 0
    report = {
        "schema_version": SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "authorization_attested": True,
        "network_access": "prohibited",
        "inputs": inputs,
        "input_rows": input_rows,
        "accepted_rows": accepted_rows,
        "duplicate_rows": duplicate_rows,
        "missing_rows": missing_rows,
        "invalid_rows": invalid_rows,
        "issues": sorted(issues, key=lambda issue: (issue["source"], issue["row"], issue["code"])),
        "athletes": len(athletes),
        "coverage": coverage,
        "missing_ivy_programs": missing_ivy_programs,
        "ivy_complete": ivy_complete,
        "row_quality_passed": row_quality_passed,
        "quality_passed": row_quality_passed and ivy_complete,
    }
    dataset = {
        "schema_version": SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "athletes": athletes,
    }
    return dataset, report


def _stage_json(destination: Path, value: dict[str, Any]) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _stage_bytes(destination: Path, value: bytes) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_authorized_csv_dataset(
    input_paths: Iterable[str | Path],
    output_path: str | Path,
    quality_path: str | Path,
    *,
    authorized: bool = False,
    allow_rejected: bool = False,
    allow_partial_ivy: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate, stage, and atomically replace the dataset and quality files."""
    dataset, report = compile_authorized_csv(input_paths, authorized=authorized)
    if not report["row_quality_passed"] and not allow_rejected:
        raise QualityGateError(
            "missing or invalid rows rejected; use allow_rejected only after reviewing the quality report"
        )
    if not report["ivy_complete"] and not allow_partial_ivy:
        raise QualityGateError(
            "all-Ivy completeness failed; one or more school/gender programs are missing"
        )
    destinations = (Path(output_path), Path(quality_path))
    if destinations[0].resolve() == destinations[1].resolve():
        raise ValueError("dataset and quality output paths must differ")
    staged: list[tuple[Path, Path]] = []
    originals = {
        destination: destination.read_bytes() if destination.is_file() else None
        for destination in destinations
    }
    published: list[Path] = []
    try:
        staged = [
            (_stage_json(destinations[0], dataset), destinations[0]),
            (_stage_json(destinations[1], report), destinations[1]),
        ]
        for temporary, destination in staged:
            os.replace(temporary, destination)
            published.append(destination)
        return dataset, report
    except BaseException:
        for destination in reversed(published):
            original = originals[destination]
            if original is None:
                destination.unlink(missing_ok=True)
            else:
                restore = _stage_bytes(destination, original)
                try:
                    os.replace(restore, destination)
                finally:
                    restore.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
