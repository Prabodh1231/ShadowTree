// Phase 2 screenshot driver: headless Edge over CDP, 1920x1080, light and dark.
// Needs `npm run dev` (5173) and a backend on 8000 (empty DB for mode "main").
// Usage: node shoot.mjs main <sample folder> <out dir>   |   node shoot.mjs down <out dir>
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [mode, a1, a2] = process.argv.slice(2);
const SAMPLE = mode === 'main' ? a1 : null;
const OUT = mode === 'main' ? a2 : a1;
const URL_ = 'http://127.0.0.1:5173/?ai=off';
const PORT = 9344;
const EDGE = ['C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'].find(existsSync);
const profile = mkdtempSync(join(tmpdir(), 'veilfs-shots-'));
const edge = spawn(EDGE, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--window-size=1920,1080', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, nextId = 1; const pending = new Map(); let interceptSearch = null;

function send(method, params = {}) {
  const id = nextId++; ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function ev(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? 'eval failed');
  return r.result.value;
}
async function shot(name) {
  await sleep(500);
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, name + '.png'), Buffer.from(r.data, 'base64'));
  console.log('saved', name);
}
async function waitFor(expr, ms = 30000) {
  const t = Date.now();
  while (Date.now() - t < ms) { if (await ev(expr).catch(() => false)) return; await sleep(250); }
  throw new Error('timeout waiting for ' + expr);
}
async function load(scheme) {
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] });
  await send('Page.navigate', { url: URL_ });
  await sleep(1500);
}

try {
  let page;
  for (let i = 0; i < 50 && !page; i++) {
    try { page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === 'page'); } catch { await sleep(200); }
  }
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', async (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); return; }
    if (m.method === 'Fetch.requestPaused') {
      const body = Buffer.from(JSON.stringify(interceptSearch)).toString('base64');
      await send('Fetch.fulfillRequest', { requestId: m.params.requestId, responseCode: 200,
        responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, { name: 'Access-Control-Allow-Origin', value: '*' }], body });
    }
  });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });

  const type = async (id, text) => { await ev(`(() => { const e = document.getElementById('${id}'); e.focus(); e.value = ${JSON.stringify(text)}; e.dispatchEvent(new Event('input', {bubbles:true})); })()`); };

  if (mode === 'down') {
    for (const s of ['light', 'dark']) { await load(s); await waitFor(`!!document.querySelector('.state code')`); await shot(`06-backend-down-${s}`); }
  } else {
    for (const s of ['light', 'dark']) { await load(s); await waitFor(`!!document.querySelector('.state h2')`); await shot(`01-first-run-empty-${s}`); }
    // Scan once, through the UI, in light mode.
    await load('light');
    await type('root', SAMPLE);
    await ev(`document.getElementById('scan-btn').click()`);
    await waitFor(`document.querySelectorAll('.card').length >= 3`, 120000);
    await waitFor(`document.getElementById('scan-btn').textContent.startsWith('Index')`, 120000);
    await sleep(800);
    // Real search shape, to decide whether weak matches need a stand-in.
    const real = await (await fetch('http://127.0.0.1:8000/search?q=' + encodeURIComponent('money I spent'))).json();
    const cards = await (await fetch('http://127.0.0.1:8000/files')).json();
    console.log('real search shape:', Array.isArray(real) ? 'array' : Object.keys(real).join(','));
    for (const s of ['light', 'dark']) {
      await load(s);
      await waitFor(`document.querySelectorAll('.card').length >= 3`);
      await shot(`02-scanned-grid-${s}`);
      await ev(`document.querySelector('.card').click()`);
      await waitFor(`!document.getElementById('drawer').hidden && !!document.querySelector('#drawer h2')`);
      await shot(`03-drawer-${s}`);
      await ev(`document.getElementById('scrim').click()`);
      await type('q', 'money I spent');
      await ev(`document.getElementById('search-form').requestSubmit()`);
      await waitFor(`document.querySelector('.view-head h1')?.textContent.startsWith('Results')`);
      await sleep(600);
      await shot(`04-search-results-${s}`);
      // Weak matches: stand-in response when the backend does not return them yet (noted in the report).
      interceptSearch = { results: [], weak: cards.slice(0, 3).map((c, i) => ({ ...c, match: 30 - i * 4, score: (30 - i * 4) / 100 })) };
      await send('Fetch.enable', { patterns: [{ urlPattern: '*127.0.0.1:8000/search*' }] });
      await type('q', 'quantum gardening');
      await ev(`document.getElementById('search-form').requestSubmit()`);
      await waitFor(`!!document.querySelector('.grid-label')`);
      await shot(`05-search-weak-${s}`);
      await send('Fetch.disable');
    }
  }
} finally { edge.kill(); try { ws?.close(); } catch { /* */ } process.exit(0); }
