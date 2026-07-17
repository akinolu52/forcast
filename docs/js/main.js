// Top-level app. Loads a league JSON, wires the three views (Table,
// Predictor, Season), and re-renders on interactions. Supports
// switching between leagues via the header picker.

import { predict } from "./poisson.js";
import { simulateSeason } from "./simulate.js";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  league: "epl",
  data: null,
  view: "table",
  home: null,
  away: null,
  simulation: null,
};

async function loadLeague(code) {
  const res = await fetch(`data/${code}.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`data/${code}.json returned ${res.status}`);
  return res.json();
}

// --- helpers ---------------------------------------------------------

function fmtPct(x) {
  return `${(x * 100).toFixed(1)}%`;
}

function eloDelta(history) {
  if (!history || history.length < 2) return 0;
  return history[history.length - 1].elo - history[0].elo;
}

// --- rendering: header + banner --------------------------------------

function renderHeader(data) {
  $("#league-name").textContent = data.name || data.league;
  $("#season-label").textContent = `Season ${data.season_start}/${(data.season_start + 1) % 100}`;
  const generated = new Date(data.generated);
  $("#generated").textContent = `Ratings generated ${generated.toISOString().slice(0, 10)}`;
  const banner = $("#demo-banner");
  if (data.demo) {
    banner.hidden = false;
    banner.textContent = data.demo_note || "Demo dataset — real data lands once the CI cron runs.";
  } else {
    banner.hidden = true;
  }
}

// --- view: table -----------------------------------------------------

function renderTable(data) {
  const tbody = $("#table-body");
  tbody.innerHTML = "";
  const eloBy = new Map(data.teams.map(t => [t.name, t]));
  const maxElo = Math.max(...data.teams.map(t => t.elo));
  const minElo = Math.min(...data.teams.map(t => t.elo));

  data.table.forEach((row, i) => {
    const team = eloBy.get(row.name);
    const elo = team ? team.elo : 1500;
    const delta = team ? eloDelta(team.history) : 0;

    const eloPct = (elo - minElo) / Math.max(1, maxElo - minElo);
    const gd = row.gf - row.ga;
    const gdSign = gd > 0 ? "+" : "";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="pos">${i + 1}</td>
      <td class="name">${row.name}</td>
      <td class="num">${row.played}</td>
      <td class="num">${row.won}</td>
      <td class="num">${row.drawn}</td>
      <td class="num">${row.lost}</td>
      <td class="num">${row.gf}</td>
      <td class="num">${row.ga}</td>
      <td class="num">${gdSign}${gd}</td>
      <td class="num pts">${row.pts}</td>
      <td class="elo">
        <span class="elo-bar" style="--fill:${(eloPct * 100).toFixed(0)}%"></span>
        <span class="elo-num">${Math.round(elo)}</span>
        ${delta ? `<span class="elo-delta ${delta > 0 ? "up" : "down"}">${delta > 0 ? "▲" : "▼"} ${Math.abs(delta).toFixed(0)}</span>` : ""}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// --- view: predictor -------------------------------------------------

function fillTeamSelects(data) {
  const names = data.teams.map(t => t.name).sort();
  for (const which of ["home", "away"]) {
    const sel = $(`#pred-${which}`);
    sel.innerHTML = "";
    for (const name of names) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    }
  }
  state.home = names[0];
  state.away = names[1];
  $("#pred-home").value = state.home;
  $("#pred-away").value = state.away;
}

function renderPredictor(data) {
  if (!state.home || !state.away || state.home === state.away) {
    $("#pred-result").innerHTML = "<p class=\"muted\">Pick two different teams.</p>";
    return;
  }
  const eloBy = new Map(data.teams.map(t => [t.name, t.elo]));
  const eloH = eloBy.get(state.home);
  const eloA = eloBy.get(state.away);
  const pred = predict(eloH, eloA, data.home_advantage_elo, data.calibration);

  const barHTML = `
    <div class="outcome-bars">
      <div class="bar bar-h" style="flex-grow:${pred.pHome}">
        <span class="label">${state.home} win</span>
        <span class="pct">${fmtPct(pred.pHome)}</span>
      </div>
      <div class="bar bar-d" style="flex-grow:${pred.pDraw}">
        <span class="label">Draw</span>
        <span class="pct">${fmtPct(pred.pDraw)}</span>
      </div>
      <div class="bar bar-a" style="flex-grow:${pred.pAway}">
        <span class="label">${state.away} win</span>
        <span class="pct">${fmtPct(pred.pAway)}</span>
      </div>
    </div>
    <p class="xg-line">Expected goals: <strong>${pred.xgHome.toFixed(2)}</strong> — <strong>${pred.xgAway.toFixed(2)}</strong> · Elo edge: <strong>${Math.round(eloH - eloA + data.home_advantage_elo)}</strong></p>
  `;

  // Scoreline grid — cap display at 5x5 (the tail is negligible)
  const cap = 5;
  let gridHTML = `<div class="grid-wrap"><table class="scoregrid"><thead><tr><th></th>`;
  for (let j = 0; j <= cap; j++) gridHTML += `<th>${j}</th>`;
  gridHTML += `</tr></thead><tbody>`;
  const maxCell = Math.max(...pred.grid.slice(0, cap + 1).map(r => Math.max(...r.slice(0, cap + 1))));
  const topScorelines = [];
  for (let i = 0; i <= cap; i++) {
    gridHTML += `<tr><th>${i}</th>`;
    for (let j = 0; j <= cap; j++) {
      const p = pred.grid[i][j];
      const intensity = Math.min(1, p / maxCell);
      gridHTML += `<td class="cell" style="--i:${intensity.toFixed(3)}" title="${state.home} ${i} - ${j} ${state.away}: ${fmtPct(p)}">${fmtPct(p)}</td>`;
      topScorelines.push({ i, j, p });
    }
    gridHTML += `</tr>`;
  }
  gridHTML += `</tbody></table></div>`;

  topScorelines.sort((a, b) => b.p - a.p);
  const topThree = topScorelines.slice(0, 3).map(s => `
    <li>${state.home} <strong>${s.i}</strong>–<strong>${s.j}</strong> ${state.away} · ${fmtPct(s.p)}</li>
  `).join("");

  const legendHTML = `
    <div class="pred-side">
      <h3>Most likely scorelines</h3>
      <ol class="top-scorelines">${topThree}</ol>
      <p class="muted">Rows: ${state.home} goals. Cols: ${state.away} goals.</p>
    </div>
  `;

  $("#pred-result").innerHTML = barHTML + `<div class="pred-columns">${gridHTML}${legendHTML}</div>`;
}

// --- view: season simulator ------------------------------------------

function renderSeason(data) {
  const status = $("#sim-status");
  if (!state.simulation) {
    status.textContent = "Click Run to Monte-Carlo the remaining fixtures.";
    $("#sim-body").innerHTML = "";
    return;
  }
  status.textContent = `${state.simulation.runs.toLocaleString()} simulated seasons`;

  const rows = state.simulation.results;
  const maxTitle = Math.max(...rows.map(r => r.title), 1e-6);
  const maxTopN = Math.max(...rows.map(r => r.topN), 1e-6);
  const maxRel = Math.max(...rows.map(r => r.relegated), 1e-6);

  $("#sim-body").innerHTML = rows.map((r, i) => `
    <tr>
      <td class="pos">${i + 1}</td>
      <td class="name">${r.name}</td>
      <td class="num">${r.expectedPoints.toFixed(1)}</td>
      <td class="prob"><span class="prob-bar" style="--fill:${(r.title / maxTitle * 100).toFixed(0)}%"></span>${fmtPct(r.title)}</td>
      <td class="prob"><span class="prob-bar topn" style="--fill:${(r.topN / maxTopN * 100).toFixed(0)}%"></span>${fmtPct(r.topN)}</td>
      <td class="prob"><span class="prob-bar rel" style="--fill:${(r.relegated / maxRel * 100).toFixed(0)}%"></span>${fmtPct(r.relegated)}</td>
    </tr>
  `).join("");
}

function runSimulation(data) {
  const runs = parseInt($("#sim-runs").value, 10) || 5000;
  const status = $("#sim-status");
  status.textContent = `Running ${runs.toLocaleString()} seasons…`;
  requestAnimationFrame(() => {
    const results = simulateSeason(data, { runs, seed: 42 });
    state.simulation = { runs, results };
    renderSeason(data);
  });
}

// --- view switching --------------------------------------------------

function switchView(name) {
  state.view = name;
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === name));
  $$(".view").forEach(v => v.hidden = v.id !== `view-${name}`);
}

// --- league switching ------------------------------------------------

async function switchLeague(code) {
  if (code === state.league && state.data) return;
  state.league = code;
  state.simulation = null;

  $$(".league-btn").forEach(b => b.classList.toggle("active", b.dataset.league === code));

  $("#app").hidden = true;
  $("#loading").hidden = false;
  $("#loading").innerHTML = "<p>Loading…</p>";

  try {
    state.data = await loadLeague(code);
  } catch (e) {
    $("#loading").innerHTML = `
      <p><strong>No data yet.</strong> The pipeline hasn't produced <code>docs/data/${code}.json</code>.</p>
      <p class="muted">Run <code>python scripts/build_elo.py --league all</code> locally, or wait for the CI cron to publish.</p>
    `;
    return;
  }

  $("#loading").hidden = true;
  $("#app").hidden = false;

  renderHeader(state.data);
  renderTable(state.data);
  fillTeamSelects(state.data);
  renderPredictor(state.data);
  renderSeason(state.data);

  history.replaceState(null, "", `?league=${code}`);
}

// --- boot ------------------------------------------------------------

async function boot() {
  const params = new URLSearchParams(location.search);
  const initial = params.get("league") || "epl";
  state.league = initial;

  $$(".league-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.league === initial);
    b.addEventListener("click", () => switchLeague(b.dataset.league));
  });

  try {
    state.data = await loadLeague(initial);
  } catch (e) {
    $("#loading").innerHTML = `
      <p><strong>No data yet.</strong> The pipeline hasn't produced <code>docs/data/${initial}.json</code>.</p>
      <p class="muted">Run <code>python scripts/build_elo.py --league all</code> locally, or wait for the CI cron to publish.</p>
    `;
    return;
  }

  $("#loading").hidden = true;
  $("#app").hidden = false;

  renderHeader(state.data);
  renderTable(state.data);
  fillTeamSelects(state.data);
  renderPredictor(state.data);
  renderSeason(state.data);

  $$(".tab").forEach(t => t.addEventListener("click", () => switchView(t.dataset.view)));
  $("#pred-home").addEventListener("change", (e) => { state.home = e.target.value; renderPredictor(state.data); });
  $("#pred-away").addEventListener("change", (e) => { state.away = e.target.value; renderPredictor(state.data); });
  $("#pred-swap").addEventListener("click", () => {
    [state.home, state.away] = [state.away, state.home];
    $("#pred-home").value = state.home;
    $("#pred-away").value = state.away;
    renderPredictor(state.data);
  });
  $("#sim-run").addEventListener("click", () => runSimulation(state.data));

  history.replaceState(null, "", `?league=${initial}`);
}

boot();
