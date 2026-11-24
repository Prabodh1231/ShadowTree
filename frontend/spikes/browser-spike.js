// Phase 0 browser spike: load Redact, Gist and Emo (browser builds only, never
// the /native entry) and run one real call each, then probe a module Worker.
//
// Each package is imported dynamically: its entry instantiates a ~45 MB wasm
// core at import time (top-level await), so a static import would block the
// first paint. LiteRT.js runs from /litert-wasm/ (our origin, copied by
// scripts/copy-litert-wasm.mjs) instead of the jsDelivr default.

const LITERT_WASM_DIR = new URL('/litert-wasm/', location.href).href;
const SAMPLE =
  'Invoice for Jane Doe, 12 Elm Street, Springfield. Contact billing@example.com ' +
  'or +1 555-0142. Card ending 4242. Total due $960 for 3 ergonomic chairs.';

const out = document.getElementById('out');
out.textContent = '';
const spike = (window.__spike = {
  env: {
    userAgent: navigator.userAgent,
    crossOriginIsolated: self.crossOriginIsolated,
    jspi: 'Suspending' in WebAssembly,
    webgpu: 'gpu' in navigator,
    litertWasmDir: LITERT_WASM_DIR,
  },
  steps: [],
  done: false,
});

function render(step) {
  const div = document.createElement('div');
  div.className = `step ${step.ok || step.expectFail ? 'ok' : 'fail'}`;
  const head = document.createElement('strong');
  head.textContent = `${step.ok ? 'OK' : step.expectFail ? 'EXPECTED FAIL' : 'FAIL'} ${step.name}`;
  const pre = document.createElement('pre');
  pre.textContent = JSON.stringify(step, null, 2);
  div.append(head, pre);
  out.append(div);
}

async function step(name, fn, { expectFail = false } = {}) {
  const t0 = performance.now();
  const rec = { name, ok: false, ...(expectFail ? { expectFail } : {}) };
  try {
    Object.assign(rec, await fn());
    rec.ok = true;
  } catch (err) {
    rec.error = String(err?.stack || err);
  }
  rec.totalMs = Math.round(performance.now() - t0);
  spike.steps.push(rec);
  render(rec);
  console.log(`[spike] ${rec.ok ? 'OK' : 'FAIL'} ${name} ${rec.totalMs}ms`);
  return rec;
}

const ms = (t0) => Math.round(performance.now() - t0);

await step('Redact: Redact.load() + redaction(text)', async () => {
  let t = performance.now();
  const { Redact, DEFAULT_LABELS } = await import('@desert-ant-labs/redact');
  const importMs = ms(t);
  t = performance.now();
  const progress = [];
  const redact = await Redact.load({
    litertWasmDir: LITERT_WASM_DIR,
    onProgress: (f) => progress.push(Math.round(f * 100)),
  });
  const loadMs = ms(t);
  t = performance.now();
  const r = await redact.redaction(SAMPLE);
  const callMs = ms(t);
  return {
    importMs, loadMs, callMs,
    progressSamples: progress.length,
    isDownloaded: redact.isDownloaded(),
    defaultLabels: DEFAULT_LABELS.length,
    input: SAMPLE,
    redactedText: r.redactedText,
    items: r.items.map(({ label, original, placeholder, confidence, start, end }) =>
      ({ label, original, placeholder, confidence: +confidence.toFixed(3), start, end })),
    restoreRoundTrip: r.restore(r.redactedText) === SAMPLE,
  };
});

await step('Gist: Gist.load() + classify(text) + scores(text)', async () => {
  let t = performance.now();
  const { Gist } = await import('@desert-ant-labs/gist');
  const importMs = ms(t);
  t = performance.now();
  const gist = await Gist.load({ litertWasmDir: LITERT_WASM_DIR });
  const loadMs = ms(t);
  t = performance.now();
  const topics = await gist.classify(SAMPLE, { topK: 3 });
  const callMs = ms(t);
  const scores = await gist.scores(SAMPLE);
  const top5 = Object.entries(scores).sort((a, b) => b[1] - a[1]).slice(0, 5)
    .map(([slug, p]) => [slug, +p.toFixed(3)]);
  return { importMs, loadMs, callMs, topics, scoresTop5: top5, nScores: Object.keys(scores).length };
});

await step('Emo: Emo.load() + suggestions(text)', async () => {
  let t = performance.now();
  const { Emo } = await import('@desert-ant-labs/emo');
  const importMs = ms(t);
  t = performance.now();
  const emo = await Emo.load({ litertWasmDir: LITERT_WASM_DIR });
  const loadMs = ms(t);
  const inputs = [
    'Finance & Receipts: invoices, receipts, bills and money spent',
    'Travel plans: flights, hotels and trips',
    'Personal & Notes: journal and private notes',
  ];
  t = performance.now();
  const suggestions = [];
  for (const text of inputs) suggestions.push({ text, emoji: await emo.suggestions(text, { limit: 3 }) });
  const callMs = ms(t);
  return { importMs, loadMs, callMsFor3: callMs, suggestions };
});

function workerProbe(shim) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./spike-worker.js', import.meta.url), { type: 'module' });
    const timer = setTimeout(() => { worker.terminate(); reject(new Error('worker timed out after 120 s')); }, 120000);
    worker.onmessage = (e) => {
      clearTimeout(timer);
      worker.terminate();
      if (e.data.ok) resolve(e.data); else reject(new Error(e.data.error));
    };
    worker.onerror = (e) => { clearTimeout(timer); worker.terminate(); reject(new Error(e.message || 'worker error')); };
    worker.postMessage({ litertWasmDir: LITERT_WASM_DIR, text: 'Pay my electricity bill', shim });
  });
}

// Expected to FAIL: documents why the shim exists.
await step('Worker probe A: Emo in a module Worker, no shim', () => workerProbe(false), { expectFail: true });
await step('Worker probe B: Emo in a module Worker, importScripts shim', () => workerProbe(true));

spike.done = true;
console.log('[spike] done');
