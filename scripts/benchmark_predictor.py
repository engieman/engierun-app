#!/usr/bin/env python3
"""Run the fixed development/final next-top-list benchmark protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engierun.predictor_benchmark import evaluate_cases, select_cases
from engierun.world_athletics_data import load_world_athletics_results

DEVELOPMENT_CONFIG = {
    "case_count": 80,
    "start_date": date(2016, 1, 1),
    "end_date": date(2022, 1, 1),
    "seed": "engierun-development-stability-v1",
    "max_prior_cv": 0.0015,
}
FINAL_CONFIG = {
    "case_count": 20,
    "start_date": date(2022, 1, 1),
    "seed": "engierun-final-stability-v1",
    "max_prior_cv": 0.0015,
}
MODEL_CONFIG = {"neighbor_count": 12, "neighbor_blend": 0.2}
SOURCE_COMMIT = "9f0870f1fbf2bfc0792a1cccbb612df73809e4c0"
SOURCE_GIT_BLOB_SHA = "7da6570597887db30303b14d48750f93c686ffa9"
SOURCE_SHA256 = "fc7762060fe7727141f7c5f73edbd4387a4edea5609e4a0e967f7e84cf29d4c2"
SOURCE_RAW_URL = (
    "https://raw.githubusercontent.com/thomascamminady/world-athletics-database/"
    f"{SOURCE_COMMIT}/data/data.csv"
)


def _public_case(row: dict) -> dict:
    """Keep only minimal pseudonymous case-level evidence for the UI artifact."""
    keys = (
        "athlete_id",
        "event",
        "target_date",
        "predicted_seconds",
        "actual_seconds",
        "absolute_error_seconds",
        "absolute_percentage_error",
        "hit",
        "uncertainty_seconds",
        "confidence",
        "confidence_kind",
        "uncertainty_kind",
        "baseline_predictions",
    )
    return {key: row[key] for key in keys}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/predictor_benchmark.json"))
    args = parser.parse_args()
    source_sha256 = _sha256(args.source)
    if source_sha256 != SOURCE_SHA256:
        parser.error(
            "source SHA-256 does not match the pinned World Athletics dataset: "
            f"expected {SOURCE_SHA256}, got {source_sha256}"
        )
    records = load_world_athletics_results(args.source)
    development_cases = select_cases(
        records,
        count=DEVELOPMENT_CONFIG["case_count"],
        start_date=DEVELOPMENT_CONFIG["start_date"],
        end_date=DEVELOPMENT_CONFIG["end_date"],
        seed=DEVELOPMENT_CONFIG["seed"],
        max_prior_cv=DEVELOPMENT_CONFIG["max_prior_cv"],
    )
    development = evaluate_cases(records, development_cases, **MODEL_CONFIG)

    # Final identities are fixed solely from pre-target evidence and metadata.
    # Model settings above are constants selected using the development period.
    final_cases = select_cases(
        records,
        count=FINAL_CONFIG["case_count"],
        start_date=FINAL_CONFIG["start_date"],
        seed=FINAL_CONFIG["seed"],
        max_prior_cv=FINAL_CONFIG["max_prior_cv"],
    )
    final = evaluate_cases(records, final_cases, **MODEL_CONFIG)
    artifact = {
        "schema_version": 1,
        "title": "Explainable next recorded top-list performance benchmark",
        "source": {
            "name": "World Athletics database by Thomas Camminady",
            "repository": "https://github.com/thomascamminady/world-athletics-database",
            "commit": SOURCE_COMMIT,
            "git_blob_sha": SOURCE_GIT_BLOB_SHA,
            "raw_url": SOURCE_RAW_URL,
            "license": "MIT",
            "license_notice": "docs/third-party/world-athletics-database-LICENSE.txt",
            "csv_sha256": source_sha256,
            "raw_rows_committed": False,
        },
        "caveat": final["benchmark_caveat"],
        "limitations": [
            "The 85% hit rate is for a high-confidence cohort with prior CV <= 0.15%, not arbitrary histories.",
            "The predictor and mean-of-last-four baseline each hit 17/20 final cases; this benchmark does not establish model superiority.",
            "Target date is known retrospectively and is used for gap and season features.",
            "Confidence is a heuristic evidence score and uncertainty ranges are not calibrated prediction intervals.",
            "Pseudonymous IDs plus public event/date/mark fields are linkable public sports data, not anonymous data.",
        ],
        "protocol": {
            "accuracy_threshold_percent": 0.85,
            "minimum_prior_performances": 4,
            "maximum_cases_per_athlete": 2,
            "selection": "stable recent history (prior CV <= 0.15%), then seeded SHA-256 sample; no target values",
            "development_period": "2016-01-01 through 2021-12-31",
            "final_period": "2022-01-01 onward",
            "development_cases": 80,
            "final_cases": 20,
            **MODEL_CONFIG,
        },
        "development_metrics": development["metrics"],
        "final_metrics": final["metrics"],
        "baselines": final["baselines"],
        "leakage_checks": final["leakage_checks"],
        "cases": [_public_case(row) for row in final["cases"]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"development": development["metrics"], "final": final["metrics"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
