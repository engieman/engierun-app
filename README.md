# EngieRun

A visual collegiate-running intelligence app for athlete browsing, event-by-event head-to-head comparison, four-race form analysis, and explainable performance forecasting.

## Implemented features

- **Athlete directory:** search, gender filters, event sorting, responsive athlete cards.
- **Head-to-head:** scores every shared timed event, labels the winner, shows the exact seconds and percentage difference for each event, then reports event win share and a geometric aggregate time edge.
- **Recent form:** compares each athlete's latest four valid same-event results, rejects malformed dates and status marks, and shows averages, race details, and the form edge.
- **Predictor:** accepts four recent same-event marks or an authorized imported history and returns a point forecast, uncertainty range, explicitly heuristic evidence score, and comparable-episode count.
- **Authorized Ivy import:** offline-only canonical CSV compiler with authorization attestation, strict source URL checks, deterministic deduplication, identity/PB conflict detection, provenance hashes, atomic writes, and a fail-closed eight-school/two-gender completeness gate.
- **Public safety:** the web app is read-only. It ships no mutation route, live profile importer, or crawler.

## Current data boundary

The checked-in `data/demo_athletes.json` contains **16 clearly labeled synthetic UI fixtures**—one fictional Female and Male record for each Ivy school. They exist only so every interface can be exercised immediately; they are not real athlete results or TFRRS data.

TFRRS/FloSports' published terms do not authorize bulk scraping or republication. EngieRun therefore does not run a bulk crawler. To populate real athletes from all eight Ivy programs, obtain a licensed export or written permission from `info@tfrrs.org` (and, for terms questions, `legal@flosports.tv`), convert it to the canonical CSV format, and run the offline compiler in [`docs/AUTHORIZED_IVY_IMPORT.md`](docs/AUTHORIZED_IVY_IMPORT.md). A ready-to-send request is in [`docs/TFRRS_AUTHORIZATION_REQUEST.md`](docs/TFRRS_AUTHORIZATION_REQUEST.md).

## Local setup

```bash
cd ~/Projects/engierun-app
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
PORT=5055 .venv/bin/gunicorn --workers 2 --threads 2 \
  --bind 127.0.0.1:5055 app:app
```

Open <http://127.0.0.1:5055> and verify <http://127.0.0.1:5055/health>. With the checked-in demo dataset, health returns:

```json
{"athletes": 16, "status": "ready", "storage": "json"}
```

## Predictor validation

Frozen, time-ordered high-confidence benchmark:

- **Development:** 60/80 within 0.85% (75.0%)
- **Final holdout:** 17/20 within 0.85% (85.0%)
- **Final MAPE:** 0.5722%
- **Temporal leakage tests:** passed

The source is Thomas Camminady's MIT-licensed World Athletics database. It contains ranked/top-list marks rather than complete race histories, so the target is the **next recorded top-list performance**, not necessarily the athlete's genuine next race. This is honest surrogate validation, not TFRRS validation. The model tied mean-of-last-four on final hit count, and its displayed confidence is a heuristic—not a calibrated probability. See [`docs/predictor-benchmark.md`](docs/predictor-benchmark.md).

### Exact benchmark reproduction

Pinned source commit: `9f0870f1fbf2bfc0792a1cccbb612df73809e4c0`

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

The artifact records the source commit, Git blob SHA, raw URL, SHA-256, protocol, metrics, and pseudonymous 20-case evidence.

## Authorized all-Ivy import

```bash
.venv/bin/python scripts/compile_authorized_ivy_csv.py \
  --input /path/to/licensed-export.csv \
  --output data/generated/ivy_athletes.json \
  --quality-output data/generated/quality_report.json \
  --confirm-authorized-source
```

The command fails unless all eight schools have both Female and Male coverage and every row passes validation. `--allow-partial-ivy` exists only for explicitly reviewed development snapshots and must not be used to claim all-Ivy completeness.

Run the app against a complete compiled export:

```bash
ENGIERUN_DATASET=data/generated/ivy_athletes.json \
  PORT=5055 .venv/bin/gunicorn --bind 127.0.0.1:5055 app:app
```

## Share immediately with Cloudflare Quick Tunnel

`cloudflared` is installed on the development Mac:

```bash
cd ~/Projects/engierun-app
./scripts/share_cloudflare.sh
```

The script prints a public `https://*.trycloudflare.com` URL. It remains live while the script and Mac are running.

For a durable custom-domain tunnel:

1. Start EngieRun locally with Gunicorn on port `5055`.
2. Run `cloudflared tunnel login` and select the Cloudflare zone.
3. Run `cloudflared tunnel create engierun` and copy the tunnel UUID.
4. Create `~/.cloudflared/config.yml`:

   ```yaml
   tunnel: YOUR-TUNNEL-UUID
   credentials-file: /Users/ashtonbange/.cloudflared/YOUR-TUNNEL-UUID.json
   ingress:
     - hostname: engierun.yourdomain.com
       service: http://127.0.0.1:5055
     - service: http_status:404
   ```

5. Run `cloudflared tunnel route dns engierun engierun.yourdomain.com`.
6. Run `cloudflared tunnel run engierun` or install it as a managed service.

## Permanent Render deployment

The included `render.yaml` is a Render Blueprint:

1. Push this branch to GitHub.
2. In Render, choose **New → Blueprint**.
3. Select `Bangea/engierun-app` and apply `render.yaml`.
4. Confirm `/health` reports `ready`, `storage: json`, and 16 demo records.
5. After obtaining a complete licensed export, commit or securely provision it and change `ENGIERUN_DATASET` to its path.

## Quality commands

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app.py engierun scripts tests
.venv/bin/bandit -q -r app.py engierun scripts -x tests
bash -n scripts/share_cloudflare.sh
```

## Source and licensing notes

- Checked-in athlete fixtures are synthetic and explicitly labeled.
- World Athletics benchmark source: [`thomascamminady/world-athletics-database`](https://github.com/thomascamminady/world-athletics-database), MIT license preserved in `docs/third-party/`.
- Raw benchmark data is downloaded separately and ignored by Git.
- TFRRS parsers and the CSV compiler are local/pure; no live TFRRS bulk access is shipped.
