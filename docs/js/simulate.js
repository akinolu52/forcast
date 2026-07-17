// Monte Carlo season simulator.
//
// Given the current league table + remaining fixtures, run N seasons
// under the Poisson match model, and aggregate per-team title / top-N /
// relegation probabilities plus mean predicted final points.
//
// The predictor gives per-match H/D/A probabilities; each simulated
// match samples an outcome from those probabilities and applies league
// points to a running copy of the table.

import { predict } from "./poisson.js";

function sampleOutcome(p, rng) {
  const r = rng();
  if (r < p.pHome) return "H";
  if (r < p.pHome + p.pDraw) return "D";
  return "A";
}

function eloMap(teams) {
  const m = new Map();
  for (const t of teams) m.set(t.name, t.elo);
  return m;
}

function seedRng(seed) {
  // Small deterministic LCG so results are reproducible per Simulate click.
  let s = seed >>> 0 || 1;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function cloneTable(table) {
  const out = new Map();
  for (const row of table) {
    out.set(row.name, {
      name: row.name,
      played: row.played,
      won: row.won,
      drawn: row.drawn,
      lost: row.lost,
      gf: row.gf,
      ga: row.ga,
      pts: row.pts,
    });
  }
  return out;
}

function applyResult(table, home, away, outcome) {
  const h = table.get(home);
  const a = table.get(away);
  if (!h || !a) return;
  h.played += 1;
  a.played += 1;
  if (outcome === "H") { h.won += 1; h.pts += 3; a.lost += 1; }
  else if (outcome === "A") { a.won += 1; a.pts += 3; h.lost += 1; }
  else { h.drawn += 1; a.drawn += 1; h.pts += 1; a.pts += 1; }
}

function rankTeams(table) {
  return [...table.values()].sort((a, b) => {
    if (b.pts !== a.pts) return b.pts - a.pts;
    const gdA = a.gf - a.ga;
    const gdB = b.gf - b.ga;
    if (gdB !== gdA) return gdB - gdA;
    if (b.gf !== a.gf) return b.gf - a.gf;
    return a.name.localeCompare(b.name);
  });
}

// Infer the missing fixtures for the current season: every ordered
// (home, away) pair among current-season teams that hasn't been played
// once. Football-data.co.uk doesn't publish future rows, so we derive them.
function inferRemainingFixtures(playedList, teamNames) {
  const seen = new Set();
  for (const m of playedList) seen.add(`${m.home}::${m.away}`);
  const fixtures = [];
  for (const home of teamNames) {
    for (const away of teamNames) {
      if (home === away) continue;
      if (!seen.has(`${home}::${away}`)) {
        fixtures.push({ home, away });
      }
    }
  }
  return fixtures;
}

export function simulateSeason(data, {
  ucl = 4,
  relegation = 3,
  runs = 5000,
  seed = 42,
} = {}) {
  const elo = eloMap(data.teams);
  const homeAdv = data.home_advantage_elo;
  const cal = data.calibration;
  const teamNames = data.table.map(r => r.name);

  let fixtures = (data.fixtures && data.fixtures.length > 0)
    ? data.fixtures.slice()
    : inferRemainingFixtures(data.played || [], teamNames);

  // Pre-compute per-fixture H/D/A probabilities once — they don't
  // change from run to run.
  const precomputed = fixtures.map(f => {
    const eH = elo.get(f.home) ?? 1500;
    const eA = elo.get(f.away) ?? 1500;
    const p = predict(eH, eA, homeAdv, cal);
    return { home: f.home, away: f.away, pHome: p.pHome, pDraw: p.pDraw, pAway: p.pAway };
  });

  const rng = seedRng(seed);

  const agg = new Map();
  for (const t of teamNames) {
    agg.set(t, { name: t, title: 0, topN: 0, relegated: 0, points: 0 });
  }

  for (let run = 0; run < runs; run++) {
    const table = cloneTable(data.table);
    for (const f of precomputed) {
      const o = sampleOutcome(f, rng);
      applyResult(table, f.home, f.away, o);
    }
    const ranked = rankTeams(table);
    for (let i = 0; i < ranked.length; i++) {
      const s = agg.get(ranked[i].name);
      if (i === 0) s.title += 1;
      if (i < ucl) s.topN += 1;
      if (i >= ranked.length - relegation) s.relegated += 1;
      s.points += ranked[i].pts;
    }
  }

  return [...agg.values()].map(s => ({
    name: s.name,
    title: s.title / runs,
    topN: s.topN / runs,
    relegated: s.relegated / runs,
    expectedPoints: s.points / runs,
  })).sort((a, b) => b.expectedPoints - a.expectedPoints);
}
