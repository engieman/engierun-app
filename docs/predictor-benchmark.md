# Explainable next-performance predictor

The predictor consumes generic chronological result records and never fetches or scrapes TFRRS. Its reproducible benchmark uses Thomas Camminady's MIT-licensed [World Athletics database](https://github.com/thomascamminady/world-athletics-database) CSV outside this repository.

## Honest target label

The source is a ranked/top-list dataset, not a complete race history. The benchmark therefore predicts the **next recorded top-list performance**, which may not be the athlete's genuine next race.

## Protocol

- Four valid prior same-event records are required.
- All athlete evidence and comparable-episode outcomes are strictly before the target date.
- Case identity is selected without target performance values: pre-target CV at most 0.15%, then deterministic SHA-256 sampling.
- The retrospective target date is known and used by gap/season features; this is not an unconditional forecast when the next race date is unknown.
- Development: 80 cases from 2016-01-01 through 2021-12-31.
- Final: fixed 20 cases from 2022-01-01 onward, at most two per pseudonymous athlete.
- A hit has absolute percentage error at most 0.85%.
- Hyperparameters (`12` neighbors and `0.2` neighbor blend) were selected using development cases only.
- Every final case plus last/mean-four/median-four/weighted baselines is recorded in `data/predictor_benchmark.json`.

The stability criterion defines a high-confidence evaluation cohort and does not measure arbitrary histories. It uses only the four prior marks. The predictor tied mean-of-last-four on final hit count (17/20), so it satisfies the requested cohort acceptance criterion but does not establish model superiority. Returned confidence is a **heuristic evidence score, not a calibrated probability**; the uncertainty range is not a calibrated prediction interval. Pseudonymous case IDs remain linkable to public event/date/mark data and are not anonymous.

## Pinned source

- Commit: `9f0870f1fbf2bfc0792a1cccbb612df73809e4c0`
- Data Git blob: `7da6570597887db30303b14d48750f93c686ffa9`
- CSV SHA-256: `fc7762060fe7727141f7c5f73edbd4387a4edea5609e4a0e967f7e84cf29d4c2`
- Raw URL: `https://raw.githubusercontent.com/thomascamminady/world-athletics-database/9f0870f1fbf2bfc0792a1cccbb612df73809e4c0/data/data.csv`

## Reproduce

```bash
mkdir -p ~/.cache/engierun/open-data
curl -fL \
  https://raw.githubusercontent.com/thomascamminady/world-athletics-database/9f0870f1fbf2bfc0792a1cccbb612df73809e4c0/data/data.csv \
  -o ~/.cache/engierun/open-data/world-athletics-data.csv
printf '%s  %s\n' \
  fc7762060fe7727141f7c5f73edbd4387a4edea5609e4a0e967f7e84cf29d4c2 \
  ~/.cache/engierun/open-data/world-athletics-data.csv | shasum -a 256 -c -
.venv/bin/python scripts/benchmark_predictor.py \
  ~/.cache/engierun/open-data/world-athletics-data.csv \
  --output data/predictor_benchmark.json
```

Optional pseudonymous preprocessing (output is ignored by Git):

```bash
.venv/bin/python scripts/preprocess_world_athletics.py \
  SOURCE.csv data/world-athletics-normalized.jsonl
```
