// Drive spikes/browser-spike.html in headless Microsoft Edge over the Chrome
// DevTools Protocol, print each step's result, and list every request that left
// 127.0.0.1 (so the review can see exactly what the SDKs contact).
//
// Usage (with `npm run dev` running in another terminal):
//   node spikes/run-browser-spike.mjs [url] [screenshot.png]
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const URL_TO_OPEN = process.argv[2] ?? 'http://127.0.0.1:5173/spikes/browser-spike.html';
const SHOT = process.argv[3];
const PORT = 9333;
const EDGE = [
  process.env.EDGE_PATH,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => p && existsSync(p));
if (!EDGE) throw new Error('Microsoft Edge not found; set EDGE_PATH');

const profile = mkdtempSync(join(tmpdir(), 'veilfs-spike-'));
const edge = spawn(EDGE, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--window-size=1280,1600', 'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function json(path) {
  for (let i = 0; i < 50; i++) {
    try { return await (await fetch(`http://127.0.0.1:${PORT}${path}`)).json(); } catch { await sleep(200); }
  }
  throw new Error('DevTools endpoint did not come up');
}

const requests = [];
const consoleLines = [];
let ws;
let nextId = 1;
const pending = new Map();
function send(method, params = {}, sessionId) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

try {
  const targets = await json('/json/list');
  const page = targets.find((t) => t.type === 'page');
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  ws.addEventListener('message', async (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
      return;
    }
    const where = msg.sessionId ? 'worker' : 'page';
    if (msg.method === 'Network.requestWillBeSent') {
      requests.push({ where, method: msg.params.request.method, url: msg.params.request.url });
    } else if (msg.method === 'Runtime.consoleAPICalled') {
      consoleLines.push(`[${where}:${msg.params.type}] ` +
        msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
    } else if (msg.method === 'Runtime.exceptionThrown') {
      consoleLines.push(`[${where}:exception] ${msg.params.exceptionDetails?.exception?.description ?? msg.params.exceptionDetails?.text}`);
    } else if (msg.method === 'Target.attachedToTarget') {
      const sid = msg.params.sessionId;
      await send('Network.enable', {}, sid).catch(() => {});
      await send('Runtime.enable', {}, sid).catch(() => {});
      await send('Runtime.runIfWaitingForDebugger', {}, sid).catch(() => {});
    }
  });

  await send('Network.enable');
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
  const t0 = Date.now();
  await send('Page.navigate', { url: URL_TO_OPEN });

  let done = false;
  while (!done && Date.now() - t0 < 600_000) {
    await sleep(1000);
    const r = await send('Runtime.evaluate', { expression: 'Boolean(window.__spike && window.__spike.done)', returnByValue: true });
    done = r.result.value === true;
  }
  await sleep(8000); // background license requests
  const r = await send('Runtime.evaluate', { expression: 'JSON.stringify(window.__spike ?? null)', returnByValue: true });
  const spike = JSON.parse(r.result.value);
  if (SHOT) {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
  }

  console.log(`page: ${URL_TO_OPEN}  finished=${done}  wall=${((Date.now() - t0) / 1000).toFixed(1)}s`);
  console.log('env:', JSON.stringify(spike?.env));
  for (const s of spike?.steps ?? []) {
    console.log(`\n[${s.ok ? 'OK' : s.expectFail ? 'EXPECTED FAIL' : 'FAIL'}] ${s.name} (${s.totalMs} ms)`);
    const { name, ok, totalMs, expectFail, ...rest } = s;
    console.log(JSON.stringify(rest, null, 2));
  }
  const external = requests.filter((q) => !/^(https?:\/\/(127\.0\.0\.1|localhost)[:/]|data:|blob:|about:|chrome|edge)/.test(q.url));
  const byHost = {};
  for (const q of external) {
    const u = new URL(q.url);
    const key = `${q.where} ${q.method} ${u.host}`;
    (byHost[key] ??= new Set()).add(u.pathname.length > 90 ? u.pathname.slice(0, 90) + '...' : u.pathname);
  }
  console.log(`\nrequests total=${requests.length}, leaving 127.0.0.1=${external.length}`);
  for (const [k, paths] of Object.entries(byHost)) console.log(`  ${k}\n    ${[...paths].join('\n    ')}`);
  const noisy = consoleLines.filter((l) => !l.includes('[spike]'));
  if (noisy.length) console.log(`\nconsole (${noisy.length}):\n  ` + noisy.slice(0, 40).join('\n  '));
  process.exitCode = spike?.steps?.every((s) => s.ok || s.expectFail) ? 0 : 1;
} finally {
  try { ws?.close(); } catch {}
  edge.kill();
  await sleep(1500);
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
