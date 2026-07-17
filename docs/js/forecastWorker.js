// Web Worker for TimesFM ONNX inference.
//
// Loads a TimesFM int8 ONNX model via onnxruntime-web and runs
// autoregressive Elo trajectory forecasting with WebGPU (WASM fallback).
//
// The model file is NOT bundled with the repo (~65MB). Users can
// provide their own by placing it at docs/model/timesfm.onnx or
// specifying a URL. If the model can't be loaded, the worker posts
// an error and the main thread falls back to LocalEngine.
//
// Protocol:
//   main → worker: { type: "forecast", history: [{m, elo}], horizon: 6 }
//   worker → main: { type: "result", forecast: [{monthsAhead, point, lo, hi}] }
//   worker → main: { type: "error", message: "..." }
//   worker → main: { type: "ready" }

const MODEL_PATH = "model/timesfm.onnx";
const CONTEXT_LEN = 512;
const PATCH_SIZE = 32;

let session = null;

async function initSession() {
  try {
    if (typeof importScripts === "function") {
      importScripts(
        "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.17.0/dist/ort.min.js"
      );
    }

    if (typeof ort === "undefined") {
      throw new Error("onnxruntime-web not available");
    }

    ort.env.wasm.numThreads = 1;

    const providers = [];
    if (typeof navigator !== "undefined" && navigator.gpu) {
      providers.push("webgpu");
    }
    providers.push("wasm");

    session = await ort.InferenceSession.create(MODEL_PATH, {
      executionProviders: providers,
    });
    postMessage({ type: "ready" });
  } catch (e) {
    postMessage({ type: "error", message: `Model load failed: ${e.message}` });
  }
}

function normalize(values) {
  const n = values.length;
  const mean = values.reduce((a, b) => a + b, 0) / n;
  let variance = 0;
  for (const v of values) variance += (v - mean) ** 2;
  const std = Math.sqrt(variance / n) || 1;
  return {
    normalized: values.map(v => (v - mean) / std),
    mean,
    std,
  };
}

function padOrTruncate(arr, targetLen) {
  if (arr.length >= targetLen) return arr.slice(-targetLen);
  const pad = new Array(targetLen - arr.length).fill(0);
  return [...pad, ...arr];
}

async function runForecast(history, horizon) {
  if (!session) {
    postMessage({ type: "error", message: "No ONNX session" });
    return;
  }

  try {
    const values = history.map(h => h.elo);
    const { normalized, mean, std } = normalize(values);
    const input = padOrTruncate(normalized, CONTEXT_LEN);
    const inputTensor = new ort.Tensor("float32", new Float32Array(input), [1, CONTEXT_LEN]);

    const forecast = [];
    let context = [...input];

    for (let step = 0; step < Math.ceil(horizon / (CONTEXT_LEN / PATCH_SIZE)); step++) {
      const feeds = { input: new ort.Tensor("float32", new Float32Array(context), [1, CONTEXT_LEN]) };
      const results = await session.run(feeds);

      const outputKey = Object.keys(results)[0];
      const output = results[outputKey].data;

      const patchOutputSize = output.length / (CONTEXT_LEN / PATCH_SIZE);
      for (let i = 0; i < Math.min(horizon - forecast.length, patchOutputSize); i++) {
        const idx = i * 10 + 4;
        const q50 = output[idx] || output[i];
        const q10 = output[i * 10 + 1] || q50 - 0.5;
        const q90 = output[i * 10 + 8] || q50 + 0.5;

        forecast.push({
          monthsAhead: forecast.length + 1,
          point: Math.round((q50 * std + mean) * 10) / 10,
          lo: Math.round((q10 * std + mean) * 10) / 10,
          hi: Math.round((q90 * std + mean) * 10) / 10,
        });

        if (forecast.length >= horizon) break;
      }

      if (forecast.length >= horizon) break;
      context = [...context.slice(patchOutputSize), ...forecast.map(f => (f.point - mean) / std)];
    }

    postMessage({ type: "result", forecast: forecast.slice(0, horizon) });
  } catch (e) {
    postMessage({ type: "error", message: `Inference failed: ${e.message}` });
  }
}

onmessage = (e) => {
  if (e.data.type === "forecast") {
    runForecast(e.data.history, e.data.horizon);
  }
};

initSession();
