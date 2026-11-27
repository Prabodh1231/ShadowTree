// Thin fetch wrapper for the local ShadowTree backend.
//
// Every request except /health carries the backend's access token. 127.0.0.1 is shared by every
// program and every signed-in user on the PC, so the token is what keeps them out.
// - Desktop window: the shell picks a random port and token per launch and hands both to the page.
// - Browser: the backend prints a link with #token=...; the page keeps it for this tab only.
const DEFAULT_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
const TOKEN_KEY = 'shadowtree-token';
const conn = { base: DEFAULT_BASE, token: null };

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status; // 0 = backend not reachable, 401 = missing or wrong token
  }
}

export const apiBase = () => conn.base;
export const hasToken = () => !!conn.token;

/** Desktop: the shell's backend address and token. */
export function setConnection(base, token) {
  if (base) conn.base = base;
  conn.token = token || null;
}

/** Browser: the token from #token=... (then removed from the address bar), else this tab's copy. */
export function initBrowserToken() {
  try {
    const m = /(?:^#|&)token=([^&]+)/.exec(location.hash);
    if (m) {
      setToken(decodeURIComponent(m[1]));
      history.replaceState(null, '', location.pathname + location.search);
    } else {
      conn.token = sessionStorage.getItem(TOKEN_KEY);
    }
  } catch { /* storage blocked: the token lasts until the page reloads */ }
}

export function setToken(token) {
  conn.token = (token || '').trim() || null;
  try {
    if (conn.token) sessionStorage.setItem(TOKEN_KEY, conn.token); else sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* ignore */ }
}

async function send(path, opts = {}) {
  const headers = {};
  if (opts.body) headers['Content-Type'] = 'application/json';
  if (conn.token) headers.Authorization = `Bearer ${conn.token}`;
  let res;
  try {
    res = await fetch(conn.base + path, { ...opts, headers });
  } catch {
    throw new ApiError('Cannot reach the ShadowTree backend.', 0);
  }
  if (!res.ok) {
    let detail = '';
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? '');
    } catch { /* not JSON */ }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  return res;
}

const call = async (path, opts) => (await send(path, opts)).json();
const post = (path, body, opts = {}) => call(path, { ...opts, method: 'POST', body: JSON.stringify(body ?? {}) });

export const api = {
  health: () => call('/health'),
  folders: () => call('/folders'),
  files: (folderId) => call('/files' + (folderId != null ? `?folder_id=${folderId}` : '')),
  file: (id, opts) => call(`/files/${id}`, opts),
  patchClientMeta: (id, body, opts = {}) => call(`/files/${id}/client-meta`, { ...opts, method: 'PATCH', body: JSON.stringify(body) }),
  // A preview PNG as a Blob. An <img src> cannot send the token, so the page fetches it.
  blob: async (path, opts) => (await send(path, opts)).blob(),
  scan: (root) => post('/scan', { root }),
  scanStatus: () => call('/scan/status'),
  cancelScan: () => post('/scan/cancel'),
  clearIndex: () => post('/index/clear'),
  createFolder: (body) => post('/folders', body),
  // Tolerant: accepts the new {results, weak} shape or an old plain array.
  async search(q) {
    const r = await call('/search?q=' + encodeURIComponent(q));
    if (Array.isArray(r)) return { results: r, weak: [] };
    return { results: r.results ?? [], weak: r.weak ?? [] };
  },
  reveal: (file_id) => post('/reveal', { file_id }),
  // Opens the file in the app Windows uses for its type (like a double click in Explorer).
  openFile: (file_id) => post('/open', { file_id }),
  // Native Windows folder dialog, opened by the local backend ({path} or {path: null}).
  pickFolder: (initial) => post('/pick-folder', initial ? { initial } : {}),
  quickFolders: () => call('/quick-folders'),
};
