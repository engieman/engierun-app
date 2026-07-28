# EngieRun exploratory QA report

## Scope

- Home/dashboard
- Athlete directory and filters
- Head-to-head comparison
- Four-race recent form
- Predictor form and forecast presentation
- Health/readiness behavior
- Read-only route boundary
- Desktop and true 390×844 mobile layout

## Final result

**Pass — no unresolved functional, console, responsive-overflow, or visual-blocking defects found.**

## Evidence

- Desktop browser screenshots verified premium hierarchy, per-event seconds and percentages, overall win share and aggregate time edge, recent-form timelines, averages, and predictor output.
- Browser console: zero JavaScript errors/messages on tested pages.
- True mobile emulation via Chrome DevTools Protocol:
  - Home: `scrollWidth=375`, `clientWidth=375`
  - Athletes: `scrollWidth=375`, `clientWidth=375`
  - Compare: `scrollWidth=375`, `clientWidth=375`
  - Predictor: `scrollWidth=375`, `clientWidth=375`
  - All three navigation links fit within the client width on every page.
- Live local health: HTTP 200 with `{"athletes":16,"status":"ready","storage":"json"}`.
- Removed routes `/add` and `/import`: HTTP 404.
- Head-to-head demo showed independent percentages for 1500m, Mile, and 3000m, then overall win share and aggregate time edge.
- Recent form showed four valid dated results per athlete, average marks, and the current edge.
- Predictor POST returned a forecast, uncalibrated range, heuristic confidence, and comparable count.

## Automated gates

- 72 pytest tests passed in the project environment.
- 72 pytest tests passed from a fresh pinned-dependency virtual environment.
- Ruff passed.
- Bandit passed.
- Python compileall passed.
- Bash syntax check passed.
- `git diff --check` passed.
- Frozen benchmark reproduced 17/20 hits, 85.0%, MAPE 0.5722%.

## Data truthfulness

- Checked-in athlete fixtures are synthetic and visibly labeled on every page.
- No live TFRRS fetch/import/crawler route is shipped.
- Real all-Ivy publication requires a locally supplied authorized export and a default fail-closed completeness gate covering all eight schools and both genders.
