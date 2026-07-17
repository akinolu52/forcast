// Elo trajectory forecasting.
//
// Two engines:
// 1. LocalEngine (always available): detrend + autocorrelation-based
//    seasonality detection + linear extrapolation. Fast, no dependencies.
// 2. OnnxEngine (optional): TimesFM 70M via onnxruntime-web in a Web
//    Worker with WebGPU/WASM. More accurate but requires the ~65MB
//    model file. Falls back to LocalEngine if unavailable.
//
// Both produce a point forecast + uncertainty band per future month.

// --- LocalEngine: pure-JS fallback -----------------------------------

function linearRegression(ys) {
  const n = ys.length;
  if (n < 2) return { slope: 0, intercept: ys[0] || 1500 };
  const xMean = (n - 1) / 2;
  const yMean = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (ys[i] - yMean);
    den += (i - xMean) * (i - xMean);
  }
  const slope = den > 0 ? num / den : 0;
  return { slope, intercept: yMean - slope * xMean };
}

function detrend(ys, reg) {
  return ys.map((y, i) => y - (reg.intercept + reg.slope * i));
}

function autocorrelation(residuals, lag) {
  const n = residuals.length;
  if (lag >= n) return 0;
  const mean = residuals.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    den += (residuals[i] - mean) ** 2;
    if (i >= lag) num += (residuals[i] - mean) * (residuals[i - lag] - mean);
  }
  return den > 0 ? num / den : 0;
}

function detectSeasonality(residuals, maxLag = 24) {
  let bestLag = 0, bestAc = 0;
  for (let lag = 6; lag <= Math.min(maxLag, Math.floor(residuals.length / 2)); lag++) {
    const ac = autocorrelation(residuals, lag);
    if (ac > bestAc) { bestAc = ac; bestLag = lag; }
  }
  return bestAc > 0.15 ? bestLag : 0;
}

function stddev(arr) {
  const n = arr.length;
  if (n < 2) return 30;
  const mean = arr.reduce((a, b) => a + b, 0) / n;
  const variance = arr.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1);
  return Math.sqrt(variance);
}

export function localForecast(history, horizon = 6) {
  const ys = history.map(h => h.elo);
  const n = ys.length;
  if (n === 0) return [];

  const windowSize = Math.min(n, 36);
  const recent = ys.slice(-windowSize);
  const reg = linearRegression(recent);

  const residuals = detrend(recent, reg);
  const period = detectSeasonality(residuals);
  const sigma = stddev(residuals);

  const slopeDecay = 0.85;

  const result = [];
  for (let h = 1; h <= horizon; h++) {
    const trendIdx = windowSize - 1 + h;
    const decayedSlope = reg.slope * Math.pow(slopeDecay, h);
    let point = reg.intercept + decayedSlope * trendIdx;

    if (period > 0) {
      const seasonIdx = (recent.length - 1 + h) % period;
      if (seasonIdx < residuals.length) {
        point += residuals[seasonIdx] * 0.5;
      }
    }

    const uncertainty = sigma * Math.sqrt(h) * 0.8;

    result.push({
      monthsAhead: h,
      point: Math.round(point * 10) / 10,
      lo: Math.round((point - 1.28 * uncertainty) * 10) / 10,
      hi: Math.round((point + 1.28 * uncertainty) * 10) / 10,
    });
  }

  return result;
}

// --- OnnxEngine: Web Worker bridge -----------------------------------

let worker = null;
let workerReady = false;
let pendingResolve = null;

function ensureWorker() {
  if (worker) return;
  try {
    worker = new Worker("js/forecastWorker.js");
    worker.onmessage = (e) => {
      if (e.data.type === "ready") {
        workerReady = true;
      } else if (e.data.type === "result") {
        if (pendingResolve) pendingResolve(e.data.forecast);
        pendingResolve = null;
      } else if (e.data.type === "error") {
        workerReady = false;
        if (pendingResolve) pendingResolve(null);
        pendingResolve = null;
      }
    };
    worker.onerror = () => { workerReady = false; };
  } catch {
    worker = null;
  }
}

export function isOnnxAvailable() {
  ensureWorker();
  return workerReady;
}

export async function onnxForecast(history, horizon = 6) {
  ensureWorker();
  if (!workerReady || !worker) return null;

  return new Promise((resolve) => {
    pendingResolve = resolve;
    const timeout = setTimeout(() => {
      if (pendingResolve === resolve) {
        pendingResolve = null;
        resolve(null);
      }
    }, 10000);
    worker.postMessage({ type: "forecast", history, horizon });
  });
}

// --- Unified API -----------------------------------------------------

export async function forecastElo(history, horizon = 6) {
  const onnxResult = await onnxForecast(history, horizon);
  if (onnxResult) return { engine: "timesfm", forecast: onnxResult };
  return { engine: "local", forecast: localForecast(history, horizon) };
}

export function forecastAllTeams(teams, horizon = 6) {
  const result = new Map();
  for (const team of teams) {
    const history = team.history || [];
    const forecast = localForecast(history, horizon);
    if (forecast.length > 0) {
      result.set(team.name, {
        current: team.elo,
        projected: forecast[forecast.length - 1].point,
        forecast,
      });
    }
  }
  return result;
}
