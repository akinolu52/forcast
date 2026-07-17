# forcast

Static-site football forecasts for Europe's top leagues.

Predicts outcomes, tables, and trophy probabilities for the English Premier
League, Spanish La Liga, Italian Serie A, German Bundesliga, French Ligue 1,
and the UEFA Champions League — using an offline Elo pipeline and an
in-browser Poisson match simulator. No servers, no API keys, no runtime backend.

## Status

Under active development. See [`PLAN.md`](./PLAN.md) for the roadmap.

- [x] **M0** Bootstrap
- [ ] **M1** EPL data pipeline + Elo
- [ ] **M2** Match predictor + calibration
- [ ] **M3** EPL site v1
- [ ] **M4** Automation (weekly cron)
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
# Regenerate JSON (needs Python 3.11+)
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/build_elo.py --league EPL

# Serve the site
python -m http.server --directory docs 8000
```

## Attribution

The Elo pipeline and Poisson match model are adapted from
[vishalmysore/webForecast](https://github.com/vishalmysore/webForecast) (MIT).
Upstream notices are preserved in [`LICENSE`](./LICENSE).

Match results come from [football-data.co.uk](https://www.football-data.co.uk/).
