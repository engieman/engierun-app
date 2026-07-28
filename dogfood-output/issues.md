# EngieRun QA issues

## ISSUE-001 — Dense mobile header risk

- **Severity:** Medium
- **Status:** Fixed and verified
- **Area:** Responsive primary navigation
- **Observed:** An initial fixed-size headless screenshot suggested the three navigation links could extend beyond a narrow capture.
- **Root cause:** The first screenshot path used Chrome's minimum outer-window width and cropped it to 390px, but the header also had unnecessarily generous mobile spacing.
- **Fix:** Reduced mobile header padding, brand scale, link size, and navigation gaps.
- **Verification:** Chrome DevTools Protocol forced a true 390×844 viewport on Home, Athletes, Compare, and Predictor. Every page reported `scrollWidth == clientWidth == 375`; all navigation link right edges remained within the client width.

## ISSUE-002 — Direct predictor/benchmark scripts failed from a source checkout

- **Severity:** High
- **Status:** Fixed and covered by regression test
- **Area:** CLI entrypoints
- **Observed:** `python scripts/benchmark_predictor.py --help` failed before argument parsing because the repository root was not on `sys.path`.
- **Fix:** Both benchmark/preprocessing entrypoints now add their source-checkout root deterministically; `tests/test_scripts_cli.py` executes all direct CLI `--help` paths.
- **Verification:** Full suite and a clean virtual environment pass.

## Unresolved issues

None found in the final QA pass. The absence of real all-Ivy data is an explicit authorization/data-source blocker, not a hidden product defect; the UI displays a prominent synthetic-demo warning and the offline compiler fails incomplete imports by default.
