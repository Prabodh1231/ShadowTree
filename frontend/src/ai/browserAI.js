// Browser AI: Desert Ant Redact, Gist and Emo on the main thread.
//
// Browser builds only (never a /native entry). The three packages instantiate a
// ~46 MB wasm core at import time, so they are loaded with dynamic import() the
// first time startBrowserAI() runs, which the app calls after first paint.
// Every exported function resolves and never rejects. Each model call times out
// after 20 s and then gives null.
//
// The Desert Ant license check is left alone: nothing here sets
// __dalLicenseEndpoint or blocks events.desertant.com.

const TIMEOUT_MS = 20000;

const models = { redact: null, gist: null, emo: null };
let starting = null;

function isOff() {
  try {
    if (import.meta.env?.VITE_BROWSER_AI === 'off') return true;
    return new URLSearchParams(globalThis.location?.search ?? '').get('ai') === 'off';
  } catch {
    return false;
  }
}

function withTimeout(promise, ms = TIMEOUT_MS) {
  let timer;
  const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(null), ms); });
  return Promise.race([Promise.resolve(promise).catch(() => null), timeout])
    .finally(() => clearTimeout(timer));
}

// The model files exist under /models/<name>/ only after `npm run fetch-models`.
// Vite's preview server answers unknown paths with index.html, so a 200 with a
// text/html type does not count.
async function selfHosted(name) {
  try {
    const r = await withTimeout(fetch(`/models/${name}/${name}.tflite`, { method: 'HEAD' }), 5000);
    return !!r && r.ok && !(r.headers.get('content-type') || '').includes('text/html');
  } catch {
    return false;
  }
}

async function loadOne(name, load) {
  const opts = { litertWasmDir: new URL('/litert-wasm/', globalThis.location.href).href };
  if (await selfHosted(name)) opts.modelBaseUrl = `/models/${name}/`;
  return withTimeout(load(opts), 120000);
}

const NONE = { redact: false, gist: false, emo: false };

// Loads one model; a failure leaves it unavailable and the others still run.
async function start(name, importer, pick) {
  try {
    const mod = await importer();
    models[name] = await loadOne(name, (o) => pick(mod).load(o));
  } catch {
    models[name] = null;
  }
}

export function startBrowserAI() {
  starting ??= (async () => {
    if (isOff()) return { ...NONE };
    // One at a time: each wasm core is large and this runs on the main thread.
    await start('redact', () => import('@desert-ant-labs/redact'), (m) => m.Redact);
    await start('gist', () => import('@desert-ant-labs/gist'), (m) => m.Gist);
    await start('emo', () => import('@desert-ant-labs/emo'), (m) => m.Emo);
    return { redact: !!models.redact, gist: !!models.gist, emo: !!models.emo };
  })().catch(() => ({ ...NONE }));
  return starting;
}

export async function suggestEmoji(name, description) {
  try {
    await startBrowserAI();
    if (!models.emo) return null;
    const text = [name, description].filter(Boolean).join(': ').trim();
    if (!text) return null;
    const out = await withTimeout(models.emo.suggestions(text, { limit: 1 }));
    return out?.[0]?.emoji ?? null;
  } catch {
    return null;
  }
}

// fullFile: the GET /files/{id} body (text_excerpt, summary). Returns null when
// no model could answer.
export async function analyzeFile(fullFile) {
  try {
    await startBrowserAI();
    if (!models.redact && !models.gist) return null;
    const excerpt = fullFile?.text_excerpt ?? '';
    const result = { has_pii: false, pii_types: [], topics: [], redacted_excerpt: null };
    let answered = false;

    if (models.redact && excerpt.trim()) {
      const r = await withTimeout(models.redact.redaction(excerpt, { minimumConfidence: 0.6 }));
      if (r) {
        answered = true;
        result.has_pii = r.items.length > 0;
        result.pii_types = [...new Set(r.items.map((i) => i.label))];
        result.redacted_excerpt = r.redactedText;
      }
    }
    const gistText = [excerpt, fullFile?.summary].filter(Boolean).join('\n').trim();
    if (models.gist && gistText) {
      const g = await withTimeout(models.gist.classify(gistText, { topK: 3 }));
      if (g) {
        answered = true;
        result.topics = g.map((t) => t.name);
      }
    }
    return answered ? result : null;
  } catch {
    return null;
  }
}

// One file at a time. Skips cards whose stored sha256 already matches.
export async function runPrivacyPass(cards, { apiBase = '', signal, onUpdate } = {}) {
  const out = { status: 'ok', done: 0, skipped: 0, failed: 0 };
  try {
    const ready = await startBrowserAI();
    if (!ready.redact && !ready.gist) return { ...out, status: 'unavailable' };
    for (const card of cards ?? []) {
      if (signal?.aborted) return { ...out, status: 'aborted' };
      if (card.client_meta?.sha256 && card.client_meta.sha256 === card.sha256) {
        out.skipped++;
        continue;
      }
      try {
        const full = await (await fetch(`${apiBase}/files/${card.id}`, { signal })).json();
        const a = await analyzeFile(full);
        if (!a) { out.failed++; continue; }
        const body = { sha256: full.sha256, has_pii: a.has_pii, pii_types: a.pii_types, topics: a.topics };
        if (a.redacted_excerpt != null) body.redacted_excerpt = a.redacted_excerpt;
        const res = await fetch(`${apiBase}/files/${card.id}/client-meta`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal,
        });
        if (res.status === 409) { out.skipped++; continue; } // file changed since the GET
        if (!res.ok) { out.failed++; continue; }
        out.done++;
        try { onUpdate?.(body, card); } catch { /* a UI callback must not stop the pass */ }
      } catch (e) {
        if (signal?.aborted) return { ...out, status: 'aborted' };
        out.failed++;
      }
    }
  } catch {
    out.status = signal?.aborted ? 'aborted' : 'unavailable';
  }
  return out;
}
