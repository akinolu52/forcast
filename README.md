# forcast

Static-site football forecasts for Europe's top leagues.

Predicts outcomes, tables, and trophy probabilities for the English Premier
League, Spanish La Liga, Italian Serie A, German Bundesliga, French Ligue 1,
and the UEFA Champions League — using an offline Elo pipeline and an
in-browser Poisson match simulator. No servers, no API keys, no runtime backend.

**Live site:** https://akinolu52.github.io/forcast/

## Status

Under active development. See [`PLAN.md`](./PLAN.md) for the roadmap.

- [x] **M0** Bootstrap
- [x] **M1** EPL data pipeline + Elo
- [x] **M2** Match predictor + calibration
- [x] **M3** EPL site v1
- [x] **M4** Automation (weekly cron)
- [ ] **M5** La Liga, Serie A, Bundesliga, Ligue 1
- [ ] **M6** UCL
- [ ] **M7** TimesFM (stretch)

## How it works

1. **Offline (Python).** `scripts/fetch_data.py` downloads historical results
   from [football-data.co.uk](https://www.football-data.co.uk/).
   `scripts/build_elo.py` computes Elo ratings for every club across every
   competition in a single shared pool (so UCL matches anchor leagues
   against each other), then emits a static JSON per league into
   `docs/data/`.
2. **In-browser (JS).** The static site under `docs/` loads that JSON,
   converts Elo differences to expected goals via a per-league calibration,
   runs an independent-Poisson score model, and Monte-Carlos the remaining
   season fixtures to produce title / top-4 / relegation probabilities.

## Local development

```bash
# Python 3.11+; only external dep is httpx for the fetcher.
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt

# 1. Fetch historical CSVs (cached under ./data; current season re-downloads)
python scripts/fetch_data.py --league EPL

# 2. Build ratings and serialize docs/data/epl.json
python scripts/build_elo.py --league EPL

# 3. Verify the pipeline end-to-end without touching the network
python scripts/self_check.py

# 4. Backtest predictor vs a naive baseline (needs real data fetched in step 1)
python scripts/backtest.py --league EPL

# 5. Serve the site
python -m http.server --directory docs 8000
```

`docs/data/*.json` is regenerated from source and not committed by hand —
CI (see `.github/workflows/update.yml`, M4) refreshes it twice a week.

## Model

**Ratings.** Persistent-pool club Elo, fitted per-league home advantage,
mean-conserving promotion/relegation rollover.

**Match model.** For each fixture, the Elo difference (after the home
advantage bonus) is fed through a two-parameter linear calibration
(`mu_total`, `beta`) to produce expected goals per side. Independent
Poissons on those means give a 11×11 scoreline grid, which aggregates
to H/D/A probabilities. Two-parameter design is deliberate: the layer
above (the Monte Carlo simulator) is what turns match probabilities
into title/relegation odds, and overfitting the match layer would
inject noise there.

**Backtest.** Walk-forward on the most recent full season. Rebuilds
Elo up to but not including each matchday, refits calibration, and
scores predictions with Brier / log-loss / accuracy against a naive
"long-run global rate" baseline. Real numbers land here once CI (M4)
runs with production data.

|              | Brier  | LogLoss | Accuracy |
| ------------ | ------ | ------- | -------- |
| Model        | _tbd_  | _tbd_   | _tbd_    |
| Naive        | _tbd_  | _tbd_   | _tbd_    |

## Attribution

The Elo pipeline and Poisson match model are adapted from
[vishalmysore/webForecast](https://github.com/vishalmysore/webForecast) (MIT).
Upstream notices are preserved in [`LICENSE`](./LICENSE).

Match results come from [football-data.co.uk](https://www.football-data.co.uk/).
