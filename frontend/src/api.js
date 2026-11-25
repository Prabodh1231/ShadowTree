// Thin fetch wrapper for the local VeilFS backend.
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status; // 0 = backend not reachable
  }
}

async function call(path, opts = {}) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      ...opts,
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
    });
  } catch {
    throw new ApiError('Cannot reach the VeilFS backend.', 0);
  }
  if (!res.ok) {
    let detail = '';
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? '');
    } catch { /* not JSON */ }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  return res.json();
}

const post = (path, body) => call(path, { method: 'POST', body: JSON.stringify(body) });

export const api = {
  health: () => call('/health'),
  folders: () => call('/folders'),
  files: (folderId) => call('/files' + (folderId != null ? `?folder_id=${folderId}` : '')),
  file: (id) => call(`/files/${id}`),
  scan: (root) => post('/scan', { root }),
  scanStatus: () => call('/scan/status'),
  createFolder: (body) => post('/folders', body),
  // Tolerant: accepts the new {results, weak} shape or an old plain array.
  async search(q) {
    const r = await call('/search?q=' + encodeURIComponent(q));
    if (Array.isArray(r)) return { results: r, weak: [] };
    return { results: r.results ?? [], weak: r.weak ?? [] };
  },
  reveal: (file_id) => post('/reveal', { file_id }),
  // Native Windows folder dialog, opened by the local backend ({path} or {path: null}).
  pickFolder: (initial) => post('/pick-folder', initial ? { initial } : {}),
  quickFolders: () => call('/quick-folders'),
};
