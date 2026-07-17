# Football League Forecast — Project Plan

## Context

Adapt the ideas in [vishalmysore/webForecast](https://github.com/vishalmysore/webForecast) (MIT-licensed) — specifically its World Cup demo (`scripts/build_elo.py` Elo pipeline + `docs/wc/` Elo→Poisson match simulator) — into a club-football forecasting site covering the English Premier League, Spanish La Liga, Italian Serie A, German Bundesliga, French Ligue 1, and the UEFA Champions League.

**Decisions:**
- EPL-first vertical slice, then expand to the other leagues and UCL
- Elo + Poisson model in v1 (no TimesFM/ONNX browser model yet — stretch goal)
- Vanilla JS static site served from GitHub Pages, zero servers

## Architecture

```
forcast/
├── LICENSE                    # MIT + upstream notices (Vishal Mysore, Fareed Khan) for ported code
├── README.md
├── scripts/
│   ├── fetch_data.py          # download football-data.co.uk CSVs per league/season
│   ├── build_elo.py           # config-driven Elo builder (adapted from webForecast)
│   └── leagues.py             # league config: codes, seasons, K-factors, home advantage
├── data/                      # raw CSVs (gitignored)
├── docs/                      # GitHub Pages site (vanilla HTML/CSS/JS)
│   ├── index.html             # league picker + views
│   ├── data/epl.json          # generated: ratings, monthly Elo series, fixtures, calibration params
│   ├── poisson.js             # ported from webForecast (attributed)
│   ├── simulate.js            # in-browser Monte Carlo season simulator
│   └── app.js / style.css
└── .github/workflows/
    └── update.yml             # cron: refetch results, rebuild JSON, commit
```

- **Offline pipeline (Python):** fetch results → compute Elo → emit static JSON into `docs/data/`.
- **Browser (JS):** loads JSON; Poisson match model + Monte Carlo run client-side, so the site stays fully static.

## Key design points

- **Data source:** football-data.co.uk CSVs — `https://www.football-data.co.uk/mmz4281/{season}/{code}.csv`, codes `E0` (EPL), `SP1` (La Liga), `I1` (Serie A), `D1` (Bundesliga), `F1` (Ligue 1); history from ~1995 for stable ratings. UCL results are not on football-data.co.uk → use [footballcsv](https://github.com/footballcsv) / openfootball in the UCL milestone.
- **Elo (club adaptations of webForecast's formula):** base 1500; K by competition (UCL knockout > UCL league phase > domestic league); goal-difference multiplier G as in the original; **home advantage fitted per league** from historical home-win rates instead of a fixed 100; **promoted teams** enter at a league-floor rating (mean of the previous season's relegated teams) rather than 1500; one shared Elo pool across all competitions so UCL matches anchor leagues against each other.
- **Match model:** Elo difference → expected goals for each side (calibrated by regression on historical results: goal difference and total goals vs Elo gap), then independent Poissons → full scoreline probability grid → win/draw/loss probabilities.
- **Season simulator:** Monte Carlo (10k runs) over remaining fixtures → P(title), P(top 4), P(relegation), expected points per team.
- **Validation:** backtest on held-out recent seasons using Brier score / log-loss vs a bookmaker-odds baseline (football-data.co.uk CSVs include closing odds columns); spot-check current ratings against clubelo.com.

## Milestones & deliverables

### M0 — Bootstrap
Scaffold the tree above: LICENSE with upstream MIT notices, README, `.gitignore` (`data/`).
**Deliverable:** repo skeleton pushed. *(Manual step: enable GitHub Pages → `docs/` folder in repo settings once there's something to serve.)*

### M1 — EPL data pipeline + Elo
`fetch_data.py` (download + cache EPL CSVs 1995→current), `build_elo.py` (Elo with club adaptations), emit `docs/data/epl.json`: per-team current Elo, monthly Elo series, played + remaining fixtures, league table.
**Deliverable:** `epl.json` generated; ratings sanity-checked against clubelo.com.

### M2 — Match predictor + calibration
Fit Elo→goals calibration on historical EPL data; port `poisson.js`; backtest script reporting Brier/log-loss vs the odds baseline on the most recent full season.
**Deliverable:** `predict(home, away) → {P(H/D/A), top scorelines}` working, with backtest numbers in the README.

### M3 — EPL site v1
`docs/` UI: league table with live Elo, head-to-head predictor (pick two teams → outcome + scoreline grid), Elo history chart (canvas), and the Monte Carlo season simulator rendering title/top-4/relegation probabilities.
**Deliverable:** working site on GitHub Pages for the EPL.

### M4 — Automation
`update.yml`: cron twice weekly (football-data.co.uk update cadence), refetch → rebuild JSON → commit if changed.
**Deliverable:** self-updating predictions, zero servers.

### M5 — Remaining domestic leagues
Make the pipeline config-driven via `leagues.py`; generate JSON for La Liga, Serie A, Bundesliga, Ligue 1; league picker in the UI; per-league home advantage and calibration.
**Deliverable:** all 5 leagues live.

### M6 — UCL
Ingest European competition results into the shared Elo pool; UCL fixture source; Swiss-format (36-team league phase + knockout) simulator; UCL tab in the UI.
**Deliverable:** UCL qualification/knockout/winner probabilities.

### M7 (stretch) — TimesFM
Port webForecast's ONNX/WebGPU worker; forecast each club's Elo trajectory and feed projected Elo into late-season simulations.

## Verification (each milestone)

- **Pipeline:** run scripts locally; assert invariants (Elo pool mean conservation, no NaNs, team counts per season, computed table matches actual standings).
- **Model:** backtest metrics (M2) must beat a "home advantage only" naive baseline and approach the bookmaker-odds baseline.
- **Site:** serve `docs/` locally and verify the table, predictor, and simulator views render and interact correctly.
- **Automation:** trigger `update.yml` manually via `workflow_dispatch` once before relying on cron.

## Working agreement

- One branch + PR per milestone (e.g. `m1-epl-pipeline`) so each deliverable is reviewable; merge before starting the next.
