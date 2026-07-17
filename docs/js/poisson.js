// Elo + Poisson match predictor.
//
// Adapted from vishalmysore/webForecast's docs/wc/poisson.js (MIT — see
// /LICENSE) and kept in sync with scripts/predictor.py. Given the two
// teams' Elo ratings, a league's home-advantage bonus, and the fitted
// {mu_total, beta} calibration, produces per-side expected goals, H/D/A
// probabilities, and the full scoreline probability grid.

const MAX_GRID = 10;

export function expectedGoals(eloHome, eloAway, homeAdv, cal) {
  const d = (eloHome + homeAdv - eloAway) / 400;
  const expectedGd = cal.beta * d;
  const xgHome = Math.max(0.05, cal.mu_total / 2 + expectedGd / 2);
  const xgAway = Math.max(0.05, cal.mu_total / 2 - expectedGd / 2);
  return { xgHome, xgAway };
}

function poissonRow(mu, n) {
  const out = new Array(n + 1);
  let p = Math.exp(-mu);
  out[0] = p;
  for (let k = 1; k <= n; k++) {
    p = (p * mu) / k;
    out[k] = p;
  }
  return out;
}

export function predict(eloHome, eloAway, homeAdv, cal, maxGoals = MAX_GRID) {
  const { xgHome, xgAway } = expectedGoals(eloHome, eloAway, homeAdv, cal);
  const ph = poissonRow(xgHome, maxGoals);
  const pa = poissonRow(xgAway, maxGoals);

  const grid = [];
  let pHome = 0;
  let pDraw = 0;
  let pAway = 0;

  for (let i = 0; i <= maxGoals; i++) {
    const row = new Array(maxGoals + 1);
    for (let j = 0; j <= maxGoals; j++) {
      const v = ph[i] * pa[j];
      row[j] = v;
      if (i > j) pHome += v;
      else if (i === j) pDraw += v;
      else pAway += v;
    }
    grid.push(row);
  }

  // Renormalise to swallow the >maxGoals tail (< 1e-6 in practice).
  const total = pHome + pDraw + pAway;
  return {
    xgHome,
    xgAway,
    pHome: pHome / total,
    pDraw: pDraw / total,
    pAway: pAway / total,
    grid,
  };
}
