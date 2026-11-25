import './styles.css';
import { api, ApiError, API_BASE } from './api.js';
import { startBrowserAI, suggestEmoji, runPrivacyPass, redactText, safeLabels, browserAIOff } from './ai/browserAI.js';
import { inTauri, waitForBackend, pickFolderNative, listenNativeDrop } from './desktop.js';
import { icon, kindIcon } from './icons.js';

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

const LAYOUTS = ['gallery', 'list', 'icons'];
function savedLayout() {
  try { const v = localStorage.getItem('veilfs-view'); if (LAYOUTS.includes(v)) return v; } catch { /* ignore */ }
  return 'gallery';
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
  layout: savedLayout(),   // 'gallery' | 'list' | 'icons'
  sel: null,               // id of the selected file
  mode: 'redacted',        // 'redacted' | 'original': which version of the text is shown
};
let passAbort = null;
let pollTimer = null;

const SENSITIVE = 'Sensitive (PII)';
const UNSORTED = 'Unsorted';
const MEDIA = 'Screenshots & Media';
const KIND_LABEL = { pdf: 'PDF document', text: 'Text file', image: 'Picture, text read from it', audio: 'Recording, transcript' };

// ---------- helpers ----------
const pct = (v) => { if (v == null || isNaN(v)) return null; return Math.round(v <= 1 ? v * 100 : v); };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const fmtSize = (b) => (b == null ? '' : b < 1024 ? b + ' B' : b < 1048576 ? Math.round(b / 1024) + ' KB' : (b / 1048576).toFixed(1) + ' MB');
// A topic-folder link under 0.5 is a best guess (soft floor). Unsorted and type links never are.
const isGuessLink = (l) => l.name !== UNSORTED && l.name !== MEDIA && l.score > 0 && l.score < 0.5;
const isGuess = (c) => (c.folders ?? []).some(isGuessLink);
const chip = (l) => {
  const guess = isGuessLink(l);
  return h('span', guess ? { class: 'chip guess', title: 'Best guess' } : { class: 'chip' }, `${l.emoji ?? ''} ${l.name}`.trim(),
    pct(l.score) > 0 && h('b', { text: pct(l.score) + '%' }));
};
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
async function refreshCards() {
  try { state.cards = await api.files(); state.down = false; state.loading = false; renderAll(); } catch { /* the job poll shows a down backend */ }
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

function visibleCards() {
  if (state.view === 'all') return state.cards;
  const f = state.folders.find((x) => x.id === state.view);
  if (f?.name === SENSITIVE) return state.cards.filter(hasPii);
  return state.cards.filter((c) => c.folders?.some((l) => l.folder_id === state.view));
}
/** The files shown right now: search results (or the closest weak ones), else the open folder. */
function currentList() {
  if (state.down || state.loading) return [];
  if (state.search) return state.search.results.length ? state.search.results : state.search.weak;
  return visibleCards();
}

function renderHead() {
  const head = $('view-head');
  head.replaceChildren();
  $('back').hidden = !(state.search || state.view !== 'all');
  if (state.down || state.loading) return;
  if (state.search) { head.append(h('small', { text: `${plural(currentList().length, 'result', 'results')} for “${state.query}”` })); return; }
  if (!state.cards.length) return;
  head.append(h('small', { text: plural(currentList().length, 'item', 'items') }));
}

function renderContent() {
  const box = $('content');
  const prev = box.querySelector('.strip, .rows, .icons');
  const keep = prev ? { l: prev.scrollLeft, t: prev.scrollTop } : null;
  box.replaceChildren();
  if (state.down) { box.append(downState()); return syncSelection([]); }
  if (state.loading) { box.append(h('div', { class: 'skeleton-strip' }, [1, 2, 3, 4, 5, 6].map(() => h('div', { class: 'skeleton' })))); return syncSelection([]); }
  if (state.search) {
    const { results, weak } = state.search;
    if (!results.length && !weak.length) {
      box.append(h('div', { class: 'state' }, h('div', { class: 'big', text: '🔍' }),
        h('h2', { text: 'No matches' }),
        h('p', { text: 'Nothing in your index is close to that. Try other words, like “receipt” or “meeting notes”.' })));
      return syncSelection([]);
    }
    if (!results.length) box.append(h('div', { class: 'grid-label', text: 'No strong matches. Closest:' }));
  } else if (!state.cards.length) {
    box.append(state.scanning ? readingState() : emptyState());
    return syncSelection([]);
  }
  const list = currentList();
  if (!list.length) {
    const f = state.folders.find((x) => x.id === state.view);
    const sens = f?.name === SENSITIVE;
    box.append(h('div', { class: 'state' },
      h('div', { class: 'big', text: sens ? '🛡️' : '📭' }),
      h('h2', { text: 'Nothing here yet' }),
      h('p', { text: sens
        ? (state.aiUnavailable ? 'The privacy scan is not available, so nothing can be flagged.' : 'Files that contain personal details (like emails or phone numbers) show up here once the privacy scan has run.')
        : 'No file matches this folder. Try “All Files” or index more files.' })));
    return syncSelection([]);
  }
  box.append(listView(list));
  const now = box.querySelector('.strip, .rows, .icons');
  if (keep && now) { now.scrollLeft = keep.l; now.scrollTop = keep.t; }
  syncSelection(list);
}

function listView(list) {
  if (state.layout === 'list') {
    return h('div', { class: 'rows', role: 'listbox', 'aria-label': 'Files' },
      h('div', { class: 'row head', 'aria-hidden': 'true' }, h('span'), h('span', { text: 'Name' }), h('span', { text: 'Filed in' }),
        h('span', { text: state.search ? 'Match' : 'Fit' }), h('span', { text: 'Size' }), h('span', { text: 'Notes' })),
      list.map((c) => itemEl(c)));
  }
  if (state.layout === 'icons') return h('div', { class: 'icons', role: 'listbox', 'aria-label': 'Files' }, list.map((c) => itemEl(c)));
  return h('div', { class: 'gallery' },
    h('div', { class: 'stage', id: 'stage' }),
    h('div', { class: 'strip', role: 'listbox', 'aria-label': 'Files', 'aria-orientation': 'horizontal' }, list.map((c) => itemEl(c))));
}

function readingState() {
  return h('div', { class: 'state' }, h('div', { class: 'big', text: '📖' }), h('h2', { text: 'Reading your files...' }),
    h('p', { text: 'Files show up here as soon as they are read.' }));
}

function emptyState() {
  return h('div', { class: 'state' },
    h('div', { class: 'big', text: '🗂️' }),
    h('h2', { text: 'Find any file by what it says, not what it’s called' }),
    h('p', { text: 'ShadowTree reads your files and sorts them into virtual folders. Your real files are never moved, changed or deleted.' }),
    h('button', { class: 'btn btn-primary btn-big', type: 'button', onclick: () => chooseFolder(), text: '📂 Choose a folder…' }),
    quickRow(),
    h('p', { class: 'hint', text: 'You can also drag a folder onto this window, or paste a path in the box on the left.' }));
}

// One-click shortcuts for the usual places (filled in once the backend answers).
let quickCache = null;
function quickRow() {
  const row = h('div', { class: 'quick-row', 'aria-label': 'Common folders' });
  const fill = (list) => {
    if (!list?.length) return;
    row.replaceChildren(h('span', { class: 'quick-label', text: 'Or start with:' }),
      ...list.map((f) => h('button', { class: 'btn btn-chip', type: 'button', title: f.path, text: QUICK_ICON[f.name] + ' ' + f.name,
        onclick: () => { $('root').value = f.path; startScan(); } })));
  };
  if (quickCache) fill(quickCache);
  else api.quickFolders().then((r) => { quickCache = r.folders; fill(quickCache); }).catch(() => {});
  return row;
}
const QUICK_ICON = { Documents: '📄', Desktop: '🖥️', Downloads: '⬇️', Pictures: '🖼️' };

// Browsers never tell a page where a folder lives, so the local backend opens
// the normal Windows "Select Folder" dialog and hands back the path.
let picking = false;
async function chooseFolder() {
  if (picking || state.scanning) return;
  picking = true;
  const btn = $('pick-btn'); const label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Pick a folder in the window…';
  try {
    const r = inTauri
      ? { path: await pickFolderNative($('root').value.trim() || null) }
      : await api.pickFolder($('root').value.trim() || null);
    if (r.path) { $('root').value = r.path; startScan(); }
  } catch (err) {
    if (err.status === 0) { state.down = true; renderAll(); }
    else toast(err.status === 409 ? 'A folder window is already open. Check your taskbar.' : err.message);
  } finally {
    picking = false; btn.disabled = false; btn.textContent = label;
  }
}

function downState() {
  return h('div', { class: 'state' },
    h('div', { class: 'big', text: '🔌' }),
    h('h2', { text: 'The ShadowTree backend is not running' }),
    h('p', { text: `This page could not reach ${API_BASE}. Start the backend in PowerShell:` }),
    h('code', { text: START_CMD }),
    h('button', { class: 'btn btn-primary', type: 'button', onclick: retryConnect, text: 'Try again' }));
}
async function retryConnect() { state.loading = true; renderAll(); await refresh(); if (!state.down) { await resumeIfRunning(); startAI(); } }

// ---------- privacy gate (fails closed) ----------
// A file's own text (summary, title, tags) is shown only after the privacy check has covered
// this exact content. Until then, or when the check failed, hung or is off: file name only.
// The check counts as running while it makes progress: LOAD_MS for the models to load,
// FILE_MS for one file (the model call timeout is 20 s).
const LOAD_MS = 65000, FILE_MS = 25000;   // LOAD_MS: just over the 60 s model load limit in browserAI.js
const privacy = { running: true, phase: 'loading', at: Date.now() };  // the first pass starts after first paint
let privacyTimer = null;
function privacyTouch(phase) {
  privacy.at = Date.now(); if (phase) privacy.phase = phase;
  clearTimeout(privacyTimer);
  privacyTimer = setTimeout(renderAll, (privacy.phase === 'loading' ? LOAD_MS : FILE_MS) + 500); // end "checking" on time
}
const isCovered = (c) => !!c.client_meta?.sha256 && c.client_meta.sha256 === c.sha256;
/** 'clear' | 'pii' | 'checking' | 'unavailable' */
function privacyState(c) {
  if (hasPii(c)) return 'pii';
  if (isCovered(c)) return 'clear';
  const limit = privacy.phase === 'loading' ? LOAD_MS : FILE_MS;
  if (state.scanning) return 'checking';   // the pass starts when the scan ends
  return privacy.running && Date.now() - privacy.at < limit ? 'checking' : 'unavailable';
}
const PRIVACY_TEXT = { checking: 'Checking privacy...', unavailable: 'Privacy check not available' };

// Card summaries of files flagged as PII use the same rule as the Redacted view:
// browser-redacted text, or a short line. Cached per id + sha256.
const cardSummaries = new Map(); // key -> string | null (null: tried, not available)
function cardSummary(c) {
  const ps = privacyState(c);
  if (ps === 'checking' || ps === 'unavailable') return PRIVACY_TEXT[ps];
  if (!c.summary) return 'No summary available.';
  if (ps === 'clear') return c.summary;
  const key = `${c.id}:${c.sha256}`;
  if (!cardSummaries.has(key)) {
    cardSummaries.set(key, null);
    redactText(c.summary).then((text) => {
      if (text == null) return;
      cardSummaries.set(key, text);
      document.querySelectorAll(`[data-id="${c.id}"] .card-summary`).forEach((p) => { p.textContent = text; });
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
  const ps = privacyState(c);
  if (ps === 'clear') return { title: c.title || c.name, keywords: c.keywords ?? [] };
  if (ps !== 'pii') return { title: c.name, keywords: [], checking: ps === 'checking' };
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
      if (state.sel === c.id) refreshSelected();
    });
  }
  return safeCache.get(key) ?? { title: c.name, keywords: [] };
}

// ---------- real previews ----------
// A picture, or the first page of a PDF, can show things the text check never saw. So a preview follows the
// same rule as the text: shown once the file is cleared by the privacy check, or when you ask for the Original.
// Otherwise the placeholder stays (a page with the redacted summary, or an icon).
const isVisual = (c) => c.kind === 'image' || c.kind === 'pdf';
const canPreview = (c) => isVisual(c) && (state.mode === 'original' || privacyState(c) === 'clear');
const previewUrl = (c, size) => `${API_BASE}/files/${c.id}/preview?size=${size}&v=${(c.sha256 ?? '').slice(0, 8)}`;
/** The picture itself. If the backend cannot make one, the image removes itself and the placeholder shows. */
const previewImg = (c, size, cls = 'thumb-img') => h('img', { class: cls, src: previewUrl(c, size), alt: '', loading: 'lazy', decoding: 'async', onerror: (e) => e.target.remove() });

// ---------- items: one file as a filmstrip card, an icon, or a list row ----------
function thumbEl(c) {
  const m = pct(c.match);
  const flags = h('span', { class: 'flags' }, hasPii(c) && h('i', { title: 'Personal details found' }), isGuess(c) && h('i', { class: 'g', title: 'Best guess' }));
  let t;
  if (c.kind === 'image') t = h('span', { class: 'thumb thumb-image' }, icon('image', 30));
  else if (c.kind === 'audio') t = h('span', { class: 'thumb thumb-audio' }, [10, 26, 16, 38, 22, 44, 18, 30, 12, 24].map((n) => h('i', { style: `height:${n}px` })));
  else t = h('span', { class: 'thumb' }, h('p', { class: 'card-summary', text: cardSummary(c) }));
  if (canPreview(c)) t.prepend(previewImg(c, 360));
  t.append(flags);
  if (m != null) t.append(h('span', { class: 'pct', text: m + '%', title: 'How well this matches your search' }));
  return t;
}
const statusText = (s) => ({ ok: 'AI summary: ok', fallback: 'Basic summary (AI was not used for this file)', error: 'AI step failed, basic summary used' }[s] ?? s);
function fitOf(c) {
  if (state.search) return pct(c.match);
  const l = (c.folders ?? []).find((x) => x.folder_id === state.view) ?? c.folders?.[0];
  return l ? pct(l.score) : null;
}

function itemEl(c) {
  cardObjs.set(c.id, c);
  const sel = state.sel === c.id;
  const status = c.ai_status ?? 'fallback';
  const dot = h('span', { class: 'dot ' + status, title: statusText(status), 'aria-label': statusText(status) });
  const common = {
    type: 'button', role: 'option', 'data-id': c.id, 'aria-selected': String(sel), tabindex: sel ? '0' : '-1',
    onclick: () => selectFile(c.id), ondblclick: () => openInApp(c.id),   // like Explorer: double click opens the file
    onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); openInApp(c.id); } },
  };
  if (state.layout === 'list') {
    const top = c.folders?.[0];
    const fit = fitOf(c);
    return h('button', { ...common, class: 'row item' },
      h('span', { class: 'rowicon' }, icon(kindIcon(c.kind), 16), canPreview(c) && previewImg(c, 96)),
      h('span', { class: 'nm' }, dot, h('span', { text: c.name, title: c.path })),
      h('span', { class: 'mute', text: top ? `${top.emoji ?? ''} ${top.name}`.trim() : '' }),
      h('span', { class: 'mute', text: fit != null ? fit + '%' : '' }),
      h('span', { class: 'mute', text: fmtSize(c.size) }),
      h('span', { class: 'flagtext' }, hasPii(c) && h('span', { class: 'pii', text: 'PII' }), isGuess(c) && h('span', { class: 'chip guess', text: 'Best guess' })));
  }
  return h('button', { ...common, class: 'card item', title: c.name },
    thumbEl(c), h('span', { class: 'card-name' }, dot, h('span', { text: c.name })));
}

function replaceCard(c) {
  document.querySelectorAll(`[data-id="${c.id}"].item`).forEach((old) => old.replaceWith(itemEl(c)));
}

async function copyPath(p) {
  try { await navigator.clipboard.writeText(p); toast('Path copied'); } catch { toast('Could not copy. Select the path and press Ctrl+C.'); }
}
/** Open the real file in the app Windows uses for it. ShadowTree only asks; it never edits the file. */
async function openInApp(id) {
  try { await api.openFile(id); toast('Opening in your default app…'); }
  catch (e) { toast(e.status === 410 ? 'That file is no longer on disk.' : e.status === 415 ? 'This kind of file can’t be opened from here.' : e.message); }
}
async function reveal(id) {
  try { await api.reveal(id); toast('Opened in File Explorer'); }
  catch (e) { toast(e.status === 410 ? 'That file is no longer on disk.' : e.message); }
}

// ---------- selection, preview page, info pane ----------
let drawerFile = null;   // the full file shown in the preview and the info pane
let loadingId = null;

function markSelected() {
  document.querySelectorAll('#content .item').forEach((el) => {
    const on = +el.dataset.id === state.sel;
    el.setAttribute('aria-selected', String(on));
    el.tabIndex = on ? 0 : -1;
    if (on) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  });
}

/** After a redraw: keep the selection if it is still listed, else select the first file. */
function syncSelection(list) {
  if (!list.length) { if (state.sel != null || drawerFile) { state.sel = null; drawerFile = null; loadingId = null; } renderStage(); renderInfo(); return; }
  if (!list.some((c) => c.id === state.sel)) { selectFile(list[0].id); return; }
  markSelected();
  if (drawerFile?.id === state.sel || loadingId === state.sel) { renderStage(); renderInfo(); } else selectFile(state.sel, { force: true });
}

async function selectFile(id, { force = false } = {}) {
  if (!force && id === state.sel && (drawerFile?.id === id || loadingId === id)) return;
  const modeWas = state.mode;
  if (id !== state.sel) setMode('redacted', false);   // every file opens covered
  state.sel = id; drawerFile = null; loadingId = id;
  if (modeWas === 'original' && state.mode === 'redacted') for (const c of currentList()) replaceCard(c);   // previews cover up again
  markSelected(); renderStage(); renderInfo();
  let f;
  try { f = await api.file(id); }
  catch (e) { f = { id, error: e.message }; }
  if (state.sel !== id) return;   // a newer selection won
  loadingId = null; drawerFile = f;
  renderStage(); renderInfo(); renderQuick();
}
/** Redraw the preview and info pane for the selected file (privacy data just changed). */
function refreshSelected() { renderStage(); renderInfo(); renderQuick(); }

const REDACTION_TOKEN = /(\[[A-Z][A-Z_]*_\d+\])/;
function withTokens(text) {
  return text.split(REDACTION_TOKEN).map((part, i) => (i % 2 ? h('mark', { class: 'tok', text: part }) : part));
}

/** The file as a page: a document, a picture frame with its text, or a recording with its transcript. */
function sheetEl(f) {
  const card = cardObjs.get(f.id) ?? f;
  const red = state.mode === 'redacted';
  const meta = card.client_meta ?? f.client_meta ?? {};
  const title = red ? safeView(card).title : (f.title || f.name);
  let body;
  if (red) {
    const ps = privacyState(card);
    body = meta.redacted_excerpt
      ? h('pre', { class: 'sheet-body' }, withTokens(meta.redacted_excerpt))
      : h('div', { class: 'sheet-body pending', text: ps === 'unavailable' ? PRIVACY_TEXT.unavailable : 'Privacy scan pending' });
  } else {
    body = h('pre', { class: 'sheet-body', text: f.text_excerpt || '(No text was read from this file.)' });
  }
  return h('article', { class: 'sheet sheet-' + f.kind },
    h('h2', { class: 'sheet-title', text: title }),
    h('div', { class: 'sheet-kind', text: KIND_LABEL[f.kind] ?? f.kind }),
    canPreview(card) && previewImg(card, 1000, 'sheet-preview'),
    f.kind === 'audio' && h('div', { class: 'wave', 'aria-hidden': 'true' },
      Array.from({ length: 40 }, (_, i) => h('i', { style: `height:${Math.round(14 + Math.abs(Math.sin(i * 0.7 + f.id) * Math.cos(i * 0.23)) * 56)}px` }))),
    body);
}

function renderStage() {
  const box = $('stage');
  if (!box) return;
  box.replaceChildren();
  const f = drawerFile;
  if (!f) { box.append(h('div', { class: 'stage-empty', text: state.sel ? 'Opening…' : '' })); return; }
  if (f.error) { box.append(h('div', { class: 'stage-empty', text: 'Could not load this file: ' + f.error })); return; }
  if (state.mode === 'original') box.append(h('div', { class: 'stage-banner', text: 'Original text. It may contain personal details.' }));
  box.append(sheetEl(f));
}

// Redacted view never shows the raw summary: it shows the Redact result, or a
// short line while that is pending, unavailable or failed.
function summaryText(f, mode) {
  if (!f.summary) return 'No summary available.';
  if (mode === 'original') return f.summary;
  if (f.redactedSummary != null) return f.redactedSummary;
  const ps = privacyState(cardObjs.get(f.id) ?? f);
  return PRIVACY_TEXT[ps] ?? 'Summary hidden in Redacted view';
}
async function redactDrawerSummary(f) {
  if (f.redactedSummary !== undefined || !f.summary) return;
  f.redactedSummary = null; // one try per open
  const text = await redactText(f.summary);
  if (text == null || drawerFile !== f) return;
  f.redactedSummary = text;
  const el = $('drawer-summary');
  if (el && state.mode === 'redacted') el.textContent = text;
}

function closeInfo() { $('drawer').classList.remove('open'); paintPanels(); }

// The folder list (left) and the details (right) can be folded away. The choice is remembered.
// In a narrow window the details are a slide-over, so the right button opens and closes that instead.
const panels = (() => {
  try { return { left: true, right: true, ...JSON.parse(localStorage.getItem('veilfs-panels')) }; } catch { return { left: true, right: true }; }
})();
const narrow = () => matchMedia('(max-width: 1100px)').matches;
function paintPanels() {
  const app = document.querySelector('.app');
  app.classList.toggle('no-left', !panels.left);
  app.classList.toggle('no-right', !panels.right);
  $('left-toggle').setAttribute('aria-expanded', String(panels.left));
  $('info-toggle').setAttribute('aria-expanded', String(narrow() ? $('drawer').classList.contains('open') : panels.right));
}
function togglePanel(side) {
  if (side === 'right' && narrow()) $('drawer').classList.toggle('open');
  else {
    panels[side] = !panels[side];
    try { localStorage.setItem('veilfs-panels', JSON.stringify(panels)); } catch { /* ignore */ }
  }
  paintPanels();
}
function renderInfo() {
  const d = $('drawer');
  d.replaceChildren(h('button', { class: 'btn btn-small info-close', type: 'button', text: 'Close ✕', onclick: closeInfo }));
  const f = drawerFile;
  if (!state.sel) { d.append(h('p', { class: 'info-empty', text: 'Select a file to see its details.' })); return; }
  if (!f) { d.append(h('div', { class: 'skeleton', style: 'height:60px;flex:none' }), h('div', { class: 'skeleton', style: 'height:110px;flex:none' })); return; }
  if (f.error) { d.append(h('div', { class: 'note err', text: 'Could not load this file: ' + f.error })); return; }
  const red = state.mode === 'redacted';
  if (red) redactDrawerSummary(f);
  const card = cardObjs.get(f.id) ?? f;
  const meta = card.client_meta ?? f.client_meta ?? {};
  const safe = safeView(card);
  const keywords = red ? safe.keywords : (f.keywords ?? []);
  const topics = (meta.topics ?? []).slice(0, 2);
  const m = pct(card.match);
  const status = f.ai_status ?? 'fallback';
  d.append(...[
    h('h2', { id: 'drawer-title', text: red ? safe.title : (f.title || f.name) }),
    h('div', { class: 'sub', text: `${KIND_LABEL[f.kind] ?? f.kind} · ${fmtSize(f.size)}` }),
    (hasPii(card) || f.folders?.length) ? h('div', { class: 'chips' },
      hasPii(card) && h('span', { class: 'pii', title: (meta.pii_types ?? []).join(', ') || 'Personal details found', text: '⚠ PII: ' + ((meta.pii_types ?? []).join(', ') || 'personal details') }),
      (f.folders ?? []).map((l) => chip(l))) : null,
    h('h3', { text: 'Summary' }),
    h('p', { class: 'full', id: 'drawer-summary', text: summaryText(f, state.mode) }),
    red && safe.checking ? h('div', { class: 'tags' }, h('span', { class: 'tag', text: 'checking…' })) : null,
    (keywords.length || topics.length) ? h('div', { class: 'tags' },
      topics.map((t) => h('span', { class: 'tag topic', text: t })),
      keywords.slice(0, 6).map((k) => h('span', { class: 'tag', text: k }))) : null,
    state.mode === 'original' ? h('p', { class: 'warn-line', text: 'This is the original text and may contain personal details.' }) : null,
    h('h3', { text: 'Details' }),
    h('dl', { class: 'meta-grid' },
      m != null ? [h('dt', { text: 'Match' }), h('dd', { text: m + '%' })] : null,
      h('dt', { text: 'Path' }), h('dd', { class: 'code', text: f.path }),
      h('dt', { text: 'Type' }), h('dd', { text: f.kind }),
      h('dt', { text: 'AI' }), h('dd', { text: { ok: 'Summarised by the AI model', fallback: 'Basic summary (AI not used)', error: 'AI failed, basic summary used' }[status] ?? status })),
    h('div', { class: 'info-actions' },
      h('button', { class: 'btn btn-primary btn-small', type: 'button', onclick: () => openInApp(f.id) }, icon('file', 14), 'Open'),
      h('button', { class: 'btn btn-small', type: 'button', onclick: () => reveal(f.id) }, icon('open', 14), 'Reveal on Disk'),
      h('button', { class: 'btn btn-small', type: 'button', onclick: () => copyPath(f.path) }, icon('copy', 14), 'Copy path')),
  ].filter(Boolean));
}

function setMode(mode, render = true) {
  state.mode = mode;
  $('mode-redacted').setAttribute('aria-pressed', String(mode === 'redacted'));
  $('mode-original').setAttribute('aria-pressed', String(mode === 'original'));
  if (render) { renderContent(); refreshSelected(); }   // thumbnails follow the mode too
}

// Full-size look at the selected file (Space).
let quickOpen = false, quickFrom = null;
function openQuick() {
  if (!drawerFile || drawerFile.error) return;
  quickFrom = document.activeElement; quickOpen = true;
  $('quick').hidden = false; renderQuick();
  $('quick').querySelector('.quick-close')?.focus();
}
function closeQuick() {
  if (!quickOpen) return;
  quickOpen = false; $('quick').hidden = true; $('quick').replaceChildren();
  if (quickFrom?.isConnected) quickFrom.focus({ preventScroll: true });
}
function renderQuick() {
  if (!quickOpen) return;
  if (!drawerFile || drawerFile.error) { $('quick').replaceChildren(h('div', { class: 'stage-empty', style: 'color:#fff', text: 'Opening…' })); return; }
  $('quick').replaceChildren(...[
    h('button', { class: 'btn quick-close', type: 'button', onclick: closeQuick }, icon('x', 14), 'Close'),
    state.mode === 'original' ? h('div', { class: 'stage-banner', text: 'Original text. It may contain personal details.' }) : null,
    sheetEl(drawerFile)].filter(Boolean));
}

function setLayout(layout) {
  state.layout = layout;
  try { localStorage.setItem('veilfs-view', layout); } catch { /* ignore */ }
  paintLayoutButtons();
  renderContent();
}
function paintLayoutButtons() {
  for (const l of LAYOUTS) $('v-' + l).setAttribute('aria-pressed', String(state.layout === l));
}

// ---------- search ----------
function clearSearch() { state.search = null; state.query = ''; $('q').value = ''; }
async function doSearch() {
  const q = $('q').value.trim();
  if (!q) { clearSearch(); return renderAll(); }
  state.query = q;
  $('content').replaceChildren(h('div', { class: 'skeleton-strip' }, [1, 2, 3].map(() => h('div', { class: 'skeleton' }))));
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
    if (s.state === 'running' || s.state === 'queued') {
      if (s.kind !== 'reclassify' && Date.now() - (tick.last ?? 0) >= 2000) { tick.last = Date.now(); await refreshCards(); }
      pollTimer = setTimeout(tick, 600); return;
    }
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

function onScan(e) { e.preventDefault(); startScan(); }

async function startScan() {
  const root = $('root').value.trim().replace(/^"(.*)"$/, '$1');  // Explorer's "Copy as path" adds quotes
  if (!root) return chooseFolder();
  $('root').value = root;
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
  privacy.running = true; privacyTouch('loading'); renderAll();
  try {
    r = await runPrivacyPass(state.cards, {
      apiBase: API_BASE, signal: ctl.signal,
      onProgress: () => privacyTouch('working'),
      onUpdate: (clientMeta, card) => {
        const id = card?.id;
        const cur = id != null ? cardById(id) : null;
        const meta2 = clientMeta ?? card.client_meta;
        // the search view may hold its own copy of the card
        const copies = [cur, cardObjs.get(id), ...(state.search ? [...state.search.results, ...state.search.weak].filter((x) => x.id === id) : [])];
        for (const x of new Set(copies.filter(Boolean))) x.client_meta = meta2 ?? x.client_meta;
        if (cur) replaceCard(cardObjs.get(id) ?? cur);
        if (state.sel === id) refreshSelected();
        clearTimeout(startPrivacyPass.t); startPrivacyPass.t = setTimeout(refreshFolders, 800);
      },
    });
  } catch { r = { status: 'unavailable' }; }
  if (ctl.signal.aborted) return;
  privacy.running = false; clearTimeout(privacyTimer); renderAll();  // whatever is still unchecked is now 'unavailable'
  if (r?.status === 'unavailable' && !state.aiUnavailable) {
    state.aiUnavailable = true;
    note('Privacy scan unavailable. Everything else works, but personal details will not be flagged.');
    renderAll();
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
// Three choices: follow Windows (no saved value), light, or dark. The button shows the current one and
// the click moves to the next.
const THEMES = ['system', 'light', 'dark'];
const THEME_ICON = { system: 'monitor', light: 'sun', dark: 'moon' };
const THEME_LABEL = { system: 'Theme: follow Windows', light: 'Theme: light', dark: 'Theme: dark' };
function currentTheme() {
  const t = document.documentElement.dataset.theme;
  return t === 'light' || t === 'dark' ? t : 'system';
}
function applyThemeLabel() {
  const t = currentTheme();
  const btn = $('theme-toggle');
  btn.replaceChildren(icon(THEME_ICON[t], 18));
  const next = THEMES[(THEMES.indexOf(t) + 1) % THEMES.length];
  btn.title = `${THEME_LABEL[t]}. Click for ${next === 'system' ? 'follow Windows' : next}.`;
  btn.setAttribute('aria-label', btn.title);
}
$('theme-toggle').addEventListener('click', () => {
  const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
  if (next === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = next;
  try { if (next === 'system') localStorage.removeItem('veilfs-theme'); else localStorage.setItem('veilfs-theme', next); } catch { /* ignore */ }
  applyThemeLabel();
  toast(THEME_LABEL[next]);
});

// ---------- boot ----------
$('back').append(icon('chevL', 18));
$('v-icons').append(icon('grid', 16)); $('v-list').append(icon('list', 16)); $('v-gallery').append(icon('gallery', 16));
$('left-toggle').append(icon('panelLeft', 18));
$('info-toggle').append(icon('panelRight', 18));
paintLayoutButtons();
paintPanels();
matchMedia('(max-width: 1100px)').addEventListener('change', paintPanels);
$('left-toggle').addEventListener('click', () => togglePanel('left'));
$('info-toggle').addEventListener('click', () => togglePanel('right'));
for (const l of LAYOUTS) $('v-' + l).addEventListener('click', () => setLayout(l));
$('back').addEventListener('click', () => { state.view = 'all'; clearSearch(); renderAll(); });
$('mode-redacted').addEventListener('click', () => setMode('redacted'));
$('mode-original').addEventListener('click', () => setMode('original'));
$('quick').addEventListener('click', (e) => { if (e.target === $('quick')) closeQuick(); });
$('scan-form').addEventListener('submit', onScan);
$('pick-btn').addEventListener('click', () => chooseFolder());
// Drag and drop: the browser hides a dropped folder's location, so a drop opens the
// picker (it also stops the browser from opening a dropped file in place of the app).
const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files');
window.addEventListener('dragover', (e) => { if (!hasFiles(e)) return; e.preventDefault(); document.body.classList.add('dropping'); });
window.addEventListener('dragleave', (e) => { if (!e.relatedTarget) document.body.classList.remove('dropping'); });
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); document.body.classList.remove('dropping');
  toast('Browsers keep a dropped folder’s location private. Pick it once in the window that opens.');
  chooseFolder();
});
$('search-form').addEventListener('submit', (e) => { e.preventDefault(); doSearch(); });
$('q').addEventListener('input', () => { if (!$('q').value.trim() && state.search) doSearch(); });
$('new-folder').addEventListener('submit', onNewFolder);
$('nf-name').addEventListener('input', onNameInput);
$('nf-desc').addEventListener('input', onNameInput);
$('nf-emoji').addEventListener('input', () => (emojiTouched = true));

// Keys work the way they do in a file manager: arrows walk the files, Enter or a double click opens the
// file, Space gives a full-size look, "/" or Ctrl+F searches, Esc steps back.
document.addEventListener('keydown', (e) => {
  const typing = e.target.matches?.('input, textarea, select, [contenteditable]');
  if (e.key === 'Escape') {
    if (quickOpen) { closeQuick(); return; }
    if ($('drawer').classList.contains('open')) { closeInfo(); return; }
    if (state.search) { clearSearch(); renderAll(); }
    return;
  }
  if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'b') { e.preventDefault(); togglePanel(e.altKey ? 'right' : 'left'); return; }
  if ((e.key === 'f' && e.ctrlKey) || (e.key === '/' && !typing)) { e.preventDefault(); $('q').focus(); $('q').select(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  const list = currentList();
  if (e.key === ' ' && list.length && (!e.target.closest?.('button') || e.target.closest('.item'))) {
    e.preventDefault(); if (quickOpen) closeQuick(); else openQuick(); return;
  }
  if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key) && list.length) {
    e.preventDefault();
    const i = Math.max(0, list.findIndex((c) => c.id === state.sel));
    const next = list[Math.min(list.length - 1, Math.max(0, i + (e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1)))];
    if (next.id !== state.sel) selectFile(next.id).then(() => { if (!quickOpen) document.querySelector(`#content [data-id="${next.id}"]`)?.focus({ preventScroll: true }); });
  }
});
try { $('root').value = localStorage.getItem('veilfs-root') ?? ''; } catch { /* ignore */ }
applyThemeLabel();
renderAll();
let backendReady = false;
waitForBackend().then(() => { backendReady = true; return refresh(); }).then(async () => { if (!state.down) { await resumeIfRunning(); } startAI(); });
// Desktop window: real dropped paths (the browser drop handler above stays for browsers).
listenNativeDrop({
  onOver: () => document.body.classList.add('dropping'),
  onLeave: () => document.body.classList.remove('dropping'),
  onDrop: (dir) => { if (!backendReady) return; if (state.scanning) return toast('A job is already running. Wait for it to finish.'); $('root').value = dir; startScan(); },
}).catch((e) => console.warn('native drop unavailable', e));
