// UCL Swiss-format simulator.
//
// Simulates the remaining league phase fixtures, then runs the
// knockout bracket (playoff round + R16 + QF + SF + Final) to
// produce per-team probabilities for:
//   - Top 8 (auto R16)
//   - Top 24 (playoff qualification)
//   - R16, QF, SF, Final, Winner

import { predict } from "./poisson.js";

function seedRng(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function sampleOutcome(pHome, pDraw, rng) {
  const r = rng();
  if (r < pHome) return "H";
  if (r < pHome + pDraw) return "D";
  return "A";
}

function sampleScore(xgHome, xgAway, rng) {
  return { hg: poissonSample(xgHome, rng), ag: poissonSample(xgAway, rng) };
}

function poissonSample(mu, rng) {
  const L = Math.exp(-mu);
  let k = 0;
  let p = 1.0;
  while (true) {
    k++;
    p *= rng();
    if (p <= L) return k - 1;
  }
}

function cloneTable(table) {
  return table.map(row => ({ ...row }));
}

function applyResult(table, home, away, outcome) {
  const h = table.find(r => r.name === home);
  const a = table.find(r => r.name === away);
  if (!h || !a) return;
  h.played += 1;
  a.played += 1;
  if (outcome === "H") { h.won += 1; h.pts += 3; a.lost += 1; }
  else if (outcome === "A") { a.won += 1; a.pts += 3; h.lost += 1; }
  else { h.drawn += 1; a.drawn += 1; h.pts += 1; a.pts += 1; }
}

function rankTable(table) {
  return table.slice().sort((a, b) => {
    if (b.pts !== a.pts) return b.pts - a.pts;
    const gdA = a.gf - a.ga;
    const gdB = b.gf - b.ga;
    if (gdB !== gdA) return gdB - gdA;
    if (b.gf !== a.gf) return b.gf - a.gf;
    return a.name.localeCompare(b.name);
  });
}

function simulateMatch(eloH, eloA, homeAdv, cal, rng) {
  const p = predict(eloH, eloA, homeAdv, cal);
  const outcome = sampleOutcome(p.pHome, p.pDraw, rng);
  return outcome;
}

function simulateKnockout(eloA, eloB, homeAdv, cal, rng) {
  const p = predict(eloA, eloB, homeAdv * 0.5, cal);
  const r = rng();
  if (r < p.pHome) return "A";
  if (r < p.pHome + p.pDraw) {
    return rng() < 0.5 ? "A" : "B";
  }
  return "B";
}

export function simulateUCL(data, { runs = 5000, seed = 42 } = {}) {
  const elo = new Map();
  for (const t of data.teams) elo.set(t.name, t.elo);
  const homeAdv = data.home_advantage_elo;
  const cal = data.calibration;
  const ko = data.knockout;

  const fixtures = data.fixtures || [];
  const precomputed = fixtures.map(f => {
    const eH = elo.get(f.home) ?? 1500;
    const eA = elo.get(f.away) ?? 1500;
    const p = predict(eH, eA, homeAdv, cal);
    return { home: f.home, away: f.away, pHome: p.pHome, pDraw: p.pDraw };
  });

  const rng = seedRng(seed);
  const teamNames = data.table.map(r => r.name);

  const agg = new Map();
  for (const t of teamNames) {
    agg.set(t, {
      name: t,
      top8: 0, top24: 0,
      r16: 0, qf: 0, sf: 0, final: 0, winner: 0,
      points: 0,
    });
  }

  for (let run = 0; run < runs; run++) {
    const table = cloneTable(data.table);
    for (const f of precomputed) {
      const o = sampleOutcome(f.pHome, f.pDraw, rng);
      applyResult(table, f.home, f.away, o);
    }
    const ranked = rankTable(table);

    for (let i = 0; i < ranked.length; i++) {
      const s = agg.get(ranked[i].name);
      s.points += ranked[i].pts;
      if (i < ko.auto_qualify) s.top8 += 1;
      if (i < ko.eliminated_below) s.top24 += 1;
    }

    const top8 = ranked.slice(0, ko.auto_qualify).map(r => r.name);
    const playoff = ranked.slice(ko.auto_qualify, ko.eliminated_below).map(r => r.name);

    const playoffWinners = [];
    for (let i = 0; i < playoff.length; i += 2) {
      if (i + 1 >= playoff.length) {
        playoffWinners.push(playoff[i]);
        break;
      }
      const a = playoff[i];
      const b = playoff[i + 1];
      const winner = simulateKnockout(
        elo.get(a) ?? 1500, elo.get(b) ?? 1500, homeAdv, cal, rng
      ) === "A" ? a : b;
      playoffWinners.push(winner);
    }

    let r16 = [];
    for (let i = 0; i < top8.length; i++) {
      const opp = playoffWinners[playoffWinners.length - 1 - i] || playoffWinners[i % playoffWinners.length];
      r16.push([top8[i], opp]);
    }

    let currentRound = r16;
    let roundLabel = "r16";
    const rounds = ["r16", "qf", "sf", "final"];
    let roundIdx = 0;

    while (currentRound.length > 0 && roundIdx < rounds.length) {
      roundLabel = rounds[roundIdx];
      const winners = [];
      for (const [a, b] of currentRound) {
        const sa = agg.get(a);
        const sb = agg.get(b);
        if (sa) sa[roundLabel] += 1;
        if (sb) sb[roundLabel] += 1;

        const w = simulateKnockout(
          elo.get(a) ?? 1500, elo.get(b) ?? 1500, homeAdv, cal, rng
        ) === "A" ? a : b;
        winners.push(w);
      }

      if (winners.length <= 1) {
        if (winners.length === 1) {
          const s = agg.get(winners[0]);
          if (s) s.winner += 1;
        }
        break;
      }

      const nextRound = [];
      for (let i = 0; i < winners.length; i += 2) {
        if (i + 1 < winners.length) {
          nextRound.push([winners[i], winners[i + 1]]);
        } else {
          nextRound.push([winners[i], winners[i]]);
        }
      }
      currentRound = nextRound;
      roundIdx++;
    }
  }

  return [...agg.values()].map(s => ({
    name: s.name,
    top8: s.top8 / runs,
    top24: s.top24 / runs,
    r16: s.r16 / runs,
    qf: s.qf / runs,
    sf: s.sf / runs,
    final: s.final / runs,
    winner: s.winner / runs,
    expectedPoints: s.points / runs,
  })).sort((a, b) => b.winner - a.winner || b.expectedPoints - a.expectedPoints);
}
