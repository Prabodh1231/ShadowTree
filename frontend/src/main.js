import './styles.css';
import { api, ApiError, API_BASE } from './api.js';
import { startBrowserAI, suggestEmoji, runPrivacyPass, redactText, safeLabels } from './ai/browserAI.js';

const $ = (id) => document.getElementById(id);
const START_CMD = 'cd "<repo>\\backend"\n.\\.venv\\Scripts\\Activate.ps1\nuvicorn app.main:app --host 127.0.0.1 --port 8000';

/** Tiny element builder. Text is always set with textContent, never innerHTML. */
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

const state = {
  folders: [],
  cards: [],          // every indexed file
  view: 'all',        // 'all' or a folder id
  query: '',
  search: null,       // {results, weak} while a search is shown
  loading: true,
  down: false,
  scanning: false,
  job: null,
  aiUnavailable: false,
};
let passAbort = null;
let pollTimer = null;

const SENSITIVE = 'Sensitive (PII)';
const UNSORTED = 'Unsorted';
const KIND_ICON = { pdf: '📄', text: '📝', image: '🖼️', audio: '🎧' };

// ---------- helpers ----------
const pct = (v) => { if (v == null || isNaN(v)) return null; return Math.round(v <= 1 ? v * 100 : v); };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2600);
}
function note(text, cls = '') {
  const n = h('div', { class: 'note ' + cls, text });
  $('notes').append(n);
  return n;
}
const cardById = (id) => state.cards.find((c) => c.id === id);
const hasPii = (c) => c.client_meta?.has_pii === true;
function folderByName(n) { return state.folders.find((f) => f.name === n); }

// ---------- data ----------
async function refresh() {
  try {
    const [folders, cards] = await Promise.all([api.folders(), api.files()]);
    state.folders = folders; state.cards = cards; state.down = false;
    if (state.view !== 'all' && !folders.some((f) => f.id === state.view)) state.view = 'all';
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) state.down = true;
    else note(e.message, 'err');
  }
  state.loading = false;
  renderAll();
}
async function refreshFolders() {
  try { state.folders = await api.folders(); renderNav(); } catch { /* ignore */ }
}

// ---------- rendering ----------
function renderAll() { renderNav(); renderHead(); renderContent(); }

function renderNav() {
  const nav = $('folder-nav');
  nav.replaceChildren();
  const item = (id, emoji, name, count) => h('button', {
    class: 'nav-item', type: 'button', 'aria-current': String(state.view === id && !state.search),
    onclick: () => { state.view = id; clearSearch(); renderAll(); },
  }, h('span', { class: 'nav-emoji', text: emoji }), h('span', { class: 'nav-name', text: name }),
  count != null && h('span', { class: 'nav-count', text: String(count) }));
  nav.append(item('all', '🗂️', 'All Files', state.cards.length));
  const sens = folderByName(SENSITIVE), uns = folderByName(UNSORTED);
  if (sens) nav.append(item(sens.id, '🛡️', 'Sensitive (PII)', sens.file_count));
  if (uns) nav.append(item(uns.id, uns.emoji || '📥', UNSORTED, uns.file_count));
  const rest = state.folders.filter((f) => f !== sens && f !== uns);
  if (rest.length) nav.append(h('div', { class: 'nav-sep', text: 'Virtual folders' }));
  for (const f of rest) nav.append(item(f.id, f.emoji || '📁', f.name, f.file_count));
}

function renderHead() {
  const head = $('view-head');
  head.replaceChildren();
  if (state.down || state.loading) return;
  if (state.search) {
    head.append(h('h1', { text: `Results for “${state.query}”` }));
    return;
  }
  if (!state.cards.length) return;
  const f = state.folders.find((x) => x.id === state.view);
  head.append(h('h1', { text: f ? `${f.emoji ?? ''} ${f.name}`.trim() : 'All Files' }),
    h('p', { text: f?.description || 'Every file VeilFS has read, in one place.' }));
}

function visibleCards() {
  if (state.view === 'all') return state.cards;
  const f = state.folders.find((x) => x.id === state.view);
  if (f?.name === SENSITIVE) return state.cards.filter(hasPii);
  return state.cards.filter((c) => c.folders?.some((l) => l.folder_id === state.view));
}

function renderContent() {
  const box = $('content');
  box.replaceChildren();
  if (state.down) return box.append(downState());
  if (state.loading) return box.append(h('div', { class: 'grid' }, [1, 2, 3, 4, 5, 6].map(() => h('div', { class: 'skeleton' }))));
  if (state.search) return box.append(...searchView());
  if (!state.cards.length) return box.append(emptyState());
  const list = visibleCards();
  if (!list.length) {
    const f = state.folders.find((x) => x.id === state.view);
    const sens = f?.name === SENSITIVE;
    return box.append(h('div', { class: 'state' },
      h('div', { class: 'big', text: sens ? '🛡️' : '📭' }),
      h('h2', { text: 'Nothing here yet' }),
      h('p', { text: sens
        ? (state.aiUnavailable ? 'The privacy scan is not available, so nothing can be flagged.' : 'Files that contain personal details (like emails or phone numbers) show up here once the privacy scan has run.')
        : 'No file matches this folder. Try “All Files” or index more files.' })));
  }
  box.append(grid(list));
}

function grid(list) { return h('div', { class: 'grid' }, list.map((c) => cardEl(c))); }

function searchView() {
  const { results, weak } = state.search;
  if (results.length) return [grid(results.map((c) => c))];
  if (weak.length) return [h('div', { class: 'grid-label', text: 'No strong matches. Closest:' }), grid(weak)];
  return [h('div', { class: 'state' }, h('div', { class: 'big', text: '🔍' }),
    h('h2', { text: 'No matches' }),
    h('p', { text: 'Nothing in your index is close to that. Try other words, like “receipt” or “meeting notes”.' }))];
}

function emptyState() {
  return h('div', { class: 'state' },
    h('div', { class: 'big', text: '🗂️' }),
    h('h2', { text: 'Find any file by what it says, not what it’s called' }),
    h('p', { text: 'VeilFS reads your files and sorts them into virtual folders. Your real files are never moved, changed or deleted.' }),
    h('ol', {},
      h('li', { text: 'Type the path of a folder in the box at the top.' }),
      h('li', { text: 'Press “Index (Read-Only)”.' }),
      h('li', { text: 'Watch your files appear here, then try the search bar.' })),
    h('button', { class: 'btn btn-primary', type: 'button', onclick: () => $('root').focus(), text: 'Choose a folder to index' }));
}

function downState() {
  return h('div', { class: 'state' },
    h('div', { class: 'big', text: '🔌' }),
    h('h2', { text: 'The VeilFS backend is not running' }),
    h('p', { text: `This page could not reach ${API_BASE}. Start the backend in PowerShell:` }),
    h('code', { text: START_CMD }),
    h('button', { class: 'btn btn-primary', type: 'button', onclick: retryConnect, text: 'Try again' }));
}
async function retryConnect() { state.loading = true; renderAll(); await refresh(); if (!state.down) { await resumeIfRunning(); startAI(); } }

// Card summaries of files flagged as PII use the same rule as the drawer's
// Redacted view: browser-redacted text, or a short line. Cached per id + sha256.
const cardSummaries = new Map(); // key -> string | null (null: tried, not available)
function cardSummary(c) {
  if (!c.summary) return 'No summary available.';
  if (!hasPii(c)) return c.summary;
  const key = `${c.id}:${c.sha256}`;
  if (!cardSummaries.has(key)) {
    cardSummaries.set(key, null);
    redactText(c.summary).then((text) => {
      if (text == null) return;
      cardSummaries.set(key, text);
      document.querySelectorAll(`[data-id="${c.id}"].card .card-summary`).forEach((p) => { p.textContent = text; });
    });
  }
  return cardSummaries.get(key) ?? 'Summary hidden: personal data';
}

// Title and keywords of PII files: redacted title, filtered keywords. Until the
// browser AI answers (or when it is off or failed) show the file name and no
// keywords. Cached per id + sha256; one file is processed at a time.
const safeCache = new Map(); // key -> {title, keywords} | null
const cardObjs = new Map();  // id -> latest card object, to redraw after the cache fills
let safeQueue = Promise.resolve();
function safeView(c) {
  if (!hasPii(c)) return { title: c.title || c.name, keywords: c.keywords ?? [] };
  const key = `${c.id}:${c.sha256}`;
  if (!safeCache.has(key)) {
    safeCache.set(key, null);
    safeQueue = safeQueue.then(async () => {
      let out = null;
      try {
        const full = await api.file(c.id);
        out = await safeLabels(full);
      } catch { /* keep the hidden view */ }
      if (!out) return;
      safeCache.set(key, out);
      const cur = cardObjs.get(c.id);
      if (cur) replaceCard(cur);
      if (drawerFile?.id === c.id) {
        const el = $('drawer-title');
        if (el && document.querySelector('.seg [aria-pressed="true"]')?.textContent === 'Redacted') el.textContent = out.title;
      }
    });
  }
  return safeCache.get(key) ?? { title: c.name, keywords: [] };
}

function cardEl(c) {
  cardObjs.set(c.id, c);
  const safe = safeView(c);
  const meta = c.client_meta ?? {};
  const topics = meta.topics ?? [];
  const status = c.ai_status ?? 'fallback';
  const statusText = { ok: 'AI summary: ok', fallback: 'Basic summary (AI was not used for this file)', error: 'AI step failed, basic summary used' }[status] ?? status;
  const m = pct(c.match);
  const el = h('article', { class: 'card', tabindex: '0', 'data-id': c.id, onclick: () => openDrawer(c.id),
    onkeydown: (e) => { if (e.key === 'Enter' && e.target === el) openDrawer(c.id); } },
  h('div', { class: 'card-top' },
    h('div', { class: 'kind', text: KIND_ICON[c.kind] ?? '📄', title: c.kind }),
    h('div', { style: 'min-width:0;flex:1' },
      h('h3', { class: 'card-title', text: safe.title }),
      h('div', { class: 'card-sub' }, h('span', { class: 'dot ' + status, title: statusText, 'aria-label': statusText }), h('span', { text: c.name }))),
    m != null && h('span', { class: 'match', text: m + '%', title: 'How well this matches your search' })),
  h('p', { class: 'card-summary', text: cardSummary(c) }),
  (safe.keywords.length || topics.length) ? h('div', { class: 'tags' },
    topics.map((t) => h('span', { class: 'tag topic', text: t })),
    safe.keywords.slice(0, 5).map((k) => h('span', { class: 'tag', text: k }))) : null,
  (c.folders?.length || hasPii(c)) ? h('div', { class: 'chips' },
    hasPii(c) && h('span', { class: 'pii', title: (meta.pii_types ?? []).join(', ') || 'Personal details found', text: '⚠ PII' }),
    (c.folders ?? []).map((l) => h('span', { class: 'chip' }, `${l.emoji ?? ''} ${l.name}`.trim(), pct(l.score) > 0 && h('b', { text: pct(l.score) + '%' })))) : null,
  h('div', { class: 'pathrow' },
    h('div', { class: 'path', title: c.path }, h('span', { text: c.path })),
    h('button', { class: 'btn btn-small', type: 'button', text: 'Copy', title: 'Copy the path', onclick: (e) => { e.stopPropagation(); copyPath(c.path); } })),
  h('div', { class: 'card-actions' },
    h('button', { class: 'btn btn-small', type: 'button', text: 'Reveal on Disk', onclick: (e) => { e.stopPropagation(); reveal(c.id); } })));
  return el;
}

function replaceCard(c) {
  document.querySelectorAll(`[data-id="${c.id}"].card`).forEach((old) => old.replaceWith(cardEl(c)));
}

async function copyPath(p) {
  try { await navigator.clipboard.writeText(p); toast('Path copied'); } catch { toast('Could not copy. Select the path and press Ctrl+C.'); }
}
async function reveal(id) {
  try { await api.reveal(id); toast('Opened in File Explorer'); }
  catch (e) { toast(e.status === 410 ? 'That file is no longer on disk.' : e.message); }
}

// ---------- drawer ----------
let drawerFile = null;
async function openDrawer(id) {
  const d = $('drawer');
  d.hidden = false; $('scrim').hidden = false;
  d.replaceChildren(h('div', { class: 'skeleton' }), h('div', { class: 'skeleton' }));
  try {
    drawerFile = await api.file(id);
    renderDrawer('redacted');
  } catch (e) {
    d.replaceChildren(closeBtn(), h('div', { class: 'note err', text: 'Could not load this file: ' + e.message }));
  }
}
function closeBtn() { return h('button', { class: 'btn btn-small drawer-close', type: 'button', text: 'Close ✕', onclick: closeDrawer }); }
function closeDrawer() { $('drawer').hidden = true; $('scrim').hidden = true; drawerFile = null; }

// Redacted view never shows the raw summary: it shows the Redact result, or a
// short line while that is pending, unavailable or failed.
function summaryText(f, mode) {
  if (!f.summary) return 'No summary available.';
  if (mode === 'original') return f.summary;
  return f.redactedSummary ?? 'Summary hidden in Redacted view';
}
async function redactDrawerSummary(f) {
  if (f.redactedSummary !== undefined || !f.summary) return;
  f.redactedSummary = null; // one try per open
  const text = await redactText(f.summary);
  if (text == null || drawerFile !== f) return;
  f.redactedSummary = text;
  const el = $('drawer-summary');
  const redactedOn = document.querySelector('.seg [aria-pressed="true"]')?.textContent === 'Redacted';
  if (el && redactedOn) el.textContent = text;
}

function renderDrawer(mode) {
  const f = drawerFile;
  if (!f) return;
  if (mode === 'redacted') redactDrawerSummary(f);
  const meta = f.client_meta ?? {};
  const redacted = meta.redacted_excerpt;
  let excerpt;
  if (mode === 'redacted') {
    excerpt = redacted ? h('pre', { class: 'excerpt', text: redacted })
      : h('div', { class: 'excerpt pending', text: 'Privacy scan pending' });
  } else {
    excerpt = h('pre', { class: 'excerpt', text: f.text_excerpt || '(No text was read from this file.)' });
  }
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Which version of the text to show' },
    h('button', { type: 'button', 'aria-pressed': String(mode === 'redacted'), text: 'Redacted', onclick: () => renderDrawer('redacted') }),
    h('button', { type: 'button', 'aria-pressed': String(mode === 'original'), text: 'Original', onclick: () => renderDrawer('original') }));
  $('drawer').replaceChildren(...[
    closeBtn(),
    h('h2', { id: 'drawer-title', text: (mode === 'redacted' && hasPii(f)) ? safeView(f).title : (f.title || f.name) }),
    h('div', { class: 'chips' }, hasPii(f) && h('span', { class: 'pii', text: '⚠ PII: ' + ((meta.pii_types ?? []).join(', ') || 'personal details') }),
      (f.folders ?? []).map((l) => h('span', { class: 'chip' }, `${l.emoji ?? ''} ${l.name}`.trim(), pct(l.score) > 0 && h('b', { text: pct(l.score) + '%' })))),
    h('h3', { text: 'Summary' }),
    h('p', { class: 'full', id: 'drawer-summary', text: summaryText(f, mode) }),
    h('h3', { text: 'Text from the file' }),
    seg,
    mode === 'original' ? h('p', { class: 'warn-line', text: 'This is the original text and may contain personal details.' }) : null,
    excerpt,
    h('h3', { text: 'Details' }),
    h('dl', { class: 'meta-grid' },
      h('dt', { text: 'Path' }), h('dd', { class: 'code', style: 'padding:4px 8px', text: f.path }),
      h('dt', { text: 'Type' }), h('dd', { text: f.kind }),
      h('dt', { text: 'AI' }), h('dd', { text: { ok: 'Summarised by the AI model', fallback: 'Basic summary (AI not used)', error: 'AI failed, basic summary used' }[f.ai_status] ?? f.ai_status })),
    h('div', { class: 'card-actions' },
      h('button', { class: 'btn btn-small', type: 'button', text: 'Reveal on Disk', onclick: () => reveal(f.id) }),
      h('button', { class: 'btn btn-small', type: 'button', text: 'Copy path', onclick: () => copyPath(f.path) }))].filter(Boolean));
}

// ---------- search ----------
function clearSearch() { state.search = null; state.query = ''; $('q').value = ''; }
async function doSearch() {
  const q = $('q').value.trim();
  if (!q) { clearSearch(); return renderAll(); }
  state.query = q;
  $('content').replaceChildren(h('div', { class: 'grid' }, [1, 2, 3].map(() => h('div', { class: 'skeleton' }))));
  try {
    const r = await api.search(q);
    if ($('q').value.trim() !== q) return; // a newer search is running
    state.search = r;
  } catch (e) {
    if (e.status === 0) { state.down = true; }
    else { state.search = null; note('Search failed: ' + e.message, 'err'); }
  }
  renderAll();
}

// ---------- scan ----------
function showProgress(s) {
  const p = $('progress');
  const running = s.state === 'running' || s.state === 'queued';
  p.hidden = !running;
  if (!running) return;
  const reclass = s.kind === 'reclassify'; // job kind text from backend/app/jobs.py
  const fill = $('bar-fill');
  const known = s.total > 0;
  fill.classList.toggle('indeterminate', !known);
  if (known) fill.style.width = Math.round((s.processed / s.total) * 100) + '%';
  $('progress-text').textContent = reclass
    ? 'Sorting your files into the new folder…'
    : known ? `Reading file ${s.processed} of ${s.total}${s.current_file ? ': ' + s.current_file : ''}` : 'Looking through the folder…';
}
function showSkipped(stats) {
  const el = $('skipped');
  const parts = [];
  if (stats?.skipped_too_large > 0) parts.push(`${plural(stats.skipped_too_large, 'file', 'files')} over 25 MB skipped`);
  if (stats?.skipped_cloud_only > 0) parts.push(`${plural(stats.skipped_cloud_only, 'cloud-only file', 'cloud-only files')} skipped (not downloaded)`);
  if (stats?.skipped_hidden_or_link > 0) parts.push(`${plural(stats.skipped_hidden_or_link, 'hidden or linked file', 'hidden or linked files')} skipped`);
  el.hidden = !parts.length;
  el.textContent = parts.join(' · ');
}

function pollJob() {
  clearTimeout(pollTimer);
  const tick = async () => {
    let s;
    try { s = await api.scanStatus(); }
    catch { state.scanning = false; state.down = true; $('progress').hidden = true; setScanBusy(false); renderAll(); return; }
    state.job = s;
    showProgress(s);
    if (s.state === 'running' || s.state === 'queued') { pollTimer = setTimeout(tick, 600); return; }
    state.scanning = false; setScanBusy(false);
    $('progress').hidden = true;
    if (s.state === 'error') note('The job stopped with an error. Some files may not have been read.', 'err');
    (s.errors ?? []).slice(0, 3).forEach((e) => note(typeof e === 'string' ? e : (e.message ?? JSON.stringify(e)), 'err'));
    if ((s.kind ?? '') !== 'reclassify') showSkipped(s.stats);
    await refresh();
    if (s.state === 'done') startPrivacyPass();
  };
  tick();
}
function setScanBusy(b) { $('scan-btn').disabled = b; $('scan-btn').textContent = b ? 'Indexing…' : 'Index (Read-Only)'; }

async function resumeIfRunning() {
  try { const s = await api.scanStatus(); if (s.state === 'running') { state.scanning = true; setScanBusy(true); pollJob(); } } catch { /* ignore */ }
}

async function onScan(e) {
  e.preventDefault();
  const root = $('root').value.trim();
  if (!root) { $('root').focus(); return toast('Type the path of a folder first.'); }
  try { localStorage.setItem('veilfs-root', root); } catch { /* ignore */ }
  passAbort?.abort();
  $('notes').replaceChildren(); showSkipped(null);
  setScanBusy(true); state.scanning = true;
  try { await api.scan(root); pollJob(); }
  catch (err) {
    state.scanning = false; setScanBusy(false);
    if (err.status === 0) { state.down = true; renderAll(); }
    else note(err.status === 409 ? 'A job is already running. Wait for it to finish.' : err.status === 400 ? `That folder can’t be indexed: ${err.message}` : err.message, 'err');
  }
}

// ---------- new folder ----------
let emojiTouched = false, emojiTimer = null;
function onNameInput() {
  clearTimeout(emojiTimer);
  if (emojiTouched || !$('nf-name').value.trim()) return;
  emojiTimer = setTimeout(async () => {
    const em = await suggestEmoji($('nf-name').value.trim(), $('nf-desc').value.trim());
    if (em && !emojiTouched) $('nf-emoji').value = em;
  }, 500);
}
async function onNewFolder(e) {
  e.preventDefault();
  const name = $('nf-name').value.trim();
  if (!name) return;
  const msg = $('nf-msg'); msg.textContent = '';
  try {
    await api.createFolder({ name, description: $('nf-desc').value.trim() || null, emoji: $('nf-emoji').value.trim() || null });
    $('nf-name').value = ''; $('nf-desc').value = ''; $('nf-emoji').value = '📁'; emojiTouched = false;
    msg.textContent = `Created “${name}”. Sorting your files into it…`;
    await refreshFolders();
    pollJob();
    setTimeout(() => (msg.textContent = ''), 5000);
  } catch (err) {
    msg.textContent = err.status === 409 ? 'You already have a folder with that name.' : err.status === 0 ? 'Backend is not running.' : err.message;
  }
}

// ---------- browser AI ----------
async function startPrivacyPass() {
  passAbort?.abort();
  const ctl = new AbortController(); passAbort = ctl;
  let r;
  try {
    r = await runPrivacyPass(state.cards, {
      apiBase: API_BASE, signal: ctl.signal,
      onUpdate: (clientMeta, card) => {
        const id = card?.id;
        const cur = id != null ? cardById(id) : null;
        if (cur) { cur.client_meta = clientMeta ?? card.client_meta ?? cur.client_meta; replaceCard(cur); }
        clearTimeout(startPrivacyPass.t); startPrivacyPass.t = setTimeout(refreshFolders, 800);
      },
    });
  } catch { r = { status: 'unavailable' }; }
  if (ctl.signal.aborted) return;
  if (r?.status === 'unavailable' && !state.aiUnavailable) {
    state.aiUnavailable = true;
    note('Privacy scan unavailable. Everything else works, but personal details will not be flagged.');
  }
  await refreshFolders();
}
function startAI() {
  // After first paint, so the page is usable while models load.
  requestAnimationFrame(() => setTimeout(async () => {
    await startBrowserAI();
    if (!state.down && state.cards.length) startPrivacyPass();
  }, 50));
}

// ---------- theme ----------
function applyThemeLabel() {
  const dark = document.documentElement.dataset.theme === 'dark'
    || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  $('theme-toggle').textContent = dark ? 'Switch to light mode' : 'Switch to dark mode';
  return dark;
}
$('theme-toggle').addEventListener('click', () => {
  const next = applyThemeLabel() ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('veilfs-theme', next); } catch { /* ignore */ }
  applyThemeLabel();
});

// ---------- boot ----------
$('scan-form').addEventListener('submit', onScan);
$('search-form').addEventListener('submit', (e) => { e.preventDefault(); doSearch(); });
$('q').addEventListener('input', () => { if (!$('q').value.trim() && state.search) doSearch(); });
$('new-folder').addEventListener('submit', onNewFolder);
$('nf-name').addEventListener('input', onNameInput);
$('nf-desc').addEventListener('input', onNameInput);
$('nf-emoji').addEventListener('input', () => (emojiTouched = true));
$('scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
try { $('root').value = localStorage.getItem('veilfs-root') ?? ''; } catch { /* ignore */ }
applyThemeLabel();
renderAll();
refresh().then(async () => { if (!state.down) { await resumeIfRunning(); } startAI(); });
