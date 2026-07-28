# Authorized local Ivy CSV import

The Ivy compiler is deliberately **offline**. It reads local CSV files and writes
static JSON; it does not discover athletes, scrape pages, follow URLs, or make
network requests.

## Authorization requirement

Do not populate an all-Ivy dataset from TFRRS/FloSports unless you have either:

- a licensed TFRRS export, or
- written permission that covers the intended collection and publication.

The checked-in `data/demo_athletes.json` contains clearly labeled synthetic UI
fixtures only. It is not TFRRS data and must never be represented as real athlete
history. Replace it with the output of this compiler only after authorization and
a successful completeness gate.

The CLI requires `--confirm-authorized-source`. This is an attestation, not a
technical substitute for obtaining permission. To request a licensed export or
written publication authorization, contact TFRRS at `info@tfrrs.org` (and
`legal@flosports.tv` for terms questions) and describe
the eight-school scope, fields, refresh frequency, and public deployment.

## Canonical CSV v1

Use UTF-8 CSV with exactly this header and one row per personal best or result:

```csv
schema_version,athlete_id,tfrrs_id,name,school,gender,year,profile_url,record_type,date,meet,event,mark,seconds,status,source_url
```

| Column | Rule |
|---|---|
| `schema_version` | Must be `1`. |
| `athlete_id` | Stable manual ID when `tfrrs_id` is absent, e.g. `manual:ivy:runner-one`. Do not use a display name alone. Optional when `tfrrs_id` exists. |
| `tfrrs_id` | Numeric TFRRS athlete ID. Required unless `athlete_id` exists. |
| `name` | Required display identity, repeated exactly on every athlete row. |
| `school` | Required and exactly one of `Brown`, `Columbia`, `Cornell`, `Dartmouth`, `Harvard`, `Penn`, `Princeton`, or `Yale`. |
| `gender` | Required and exactly `Female` or `Male`; the completeness gate requires both for every school. |
| `year` | Team/class year when known; blank is preserved as `null`. |
| `profile_url` | Required for a TFRRS ID; blank for manual IDs. Must be an exact canonical HTTPS TFRRS athlete URL and its path ID must match `tfrrs_id`. |
| `record_type` | `best` or `result`. |
| `date` | ISO `YYYY-MM-DD`; required for results, optional for bests. |
| `meet` | Required for results, optional for bests. |
| `event`, `mark` | Required. Keep the source's normalized event and display mark. |
| `seconds` | Optional positive finite decimal for timed marks. Blank for field marks and statuses. |
| `status` | Blank or one of `DNF`, `DNS`, `DQ`, `FS`, `NT`, `NH`, `NM`, `FOUL`; it must equal `mark`. |
| `source_url` | Optional exact canonical HTTPS TFRRS athlete/result URL. It is validated but never opened. |

Example:

```csv
schema_version,athlete_id,tfrrs_id,name,school,gender,year,profile_url,record_type,date,meet,event,mark,seconds,status,source_url
1,,100,Runner One,Dartmouth,Male,SO-2,https://www.tfrrs.org/athletes/100/Dartmouth/Runner_One.html,best,,,Mile,4:09.00,249.0,,https://www.tfrrs.org/athletes/100/Dartmouth/Runner_One.html
1,,100,Runner One,Dartmouth,Male,SO-2,https://www.tfrrs.org/athletes/100/Dartmouth/Runner_One.html,result,2026-01-02,Authorized Meet,Mile,4:10.00,250.0,,https://www.tfrrs.org/results/9000/Authorized_Meet.html
```

## Compile

```bash
.venv/bin/python scripts/compile_authorized_ivy_csv.py \
  --input /path/to/licensed-export.csv \
  --output data/generated/ivy_athletes.json \
  --quality-output data/generated/quality_report.json \
  --confirm-authorized-source
```

Repeat `--input` to combine authorized local files. Inputs are hashed in the
quality report. The compiler deterministically:

- deduplicates byte-equivalent canonical rows;
- groups by `tfrrs_id`, or by the manual stable ID when no TFRRS ID exists;
- preserves all unique chronological results, status marks, field marks, and PBs;
- rejects conflicting identities and conflicting PBs;
- reports missing, invalid, and duplicate rows; and
- reports unique-athlete and accepted-row coverage per school and gender; and
- fails closed unless all eight schools contain both Female and Male coverage.

Missing or invalid rows fail the publication quality gate. Missing school/gender
programs also fail publication. `--allow-rejected` and `--allow-partial-ivy` are
explicit development-only overrides after diagnostics are reviewed; neither may
be used to claim a complete all-Ivy release. Identity conflicts always fail.
Dataset and quality JSON files are fully staged,
`fsync`ed, and replaced with rollback if publication fails. Output athletes use
the static UI-compatible fields `id`, `name`, `school`, `gender`, `year`,
`profile_url`, `bests`, and `results`.
