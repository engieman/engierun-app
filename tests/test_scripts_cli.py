import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_direct_cli_entrypoints_can_be_run_from_a_source_checkout():
    for relative in (
        "scripts/benchmark_predictor.py",
        "scripts/preprocess_world_athletics.py",
        "scripts/compile_authorized_ivy_csv.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(ROOT / relative), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()


def test_benchmark_cli_rejects_any_source_that_does_not_match_pinned_sha256(
    tmp_path,
):
    source = tmp_path / "tampered.csv"
    source.write_text("Event;Result\n1500 Metres;4:00.00\n", encoding="utf-8")
    output = tmp_path / "benchmark.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmark_predictor.py"),
            str(source),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 2
    assert "source SHA-256 does not match" in completed.stderr
    assert not output.exists()
