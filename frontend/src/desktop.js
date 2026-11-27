// Desktop (Tauri) helpers. In a normal browser every function here is a no-op, and
// the Tauri modules are loaded with dynamic import so the browser build never needs them.
export const inTauri = typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Full-window message shown while the backend starts (or failed to start). */
function overlay() {
  let el = document.getElementById('desktop-boot');
  if (!el) {
    el = document.createElement('div');
    el.id = 'desktop-boot';
    el.setAttribute('role', 'status');
    el.style.cssText = 'position:fixed;inset:0;z-index:9999;display:grid;place-content:center;gap:12px;' +
      'text-align:center;background:var(--bg,#0f1115);color:var(--fg,#e8e8ea);font:16px system-ui,sans-serif;padding:24px';
    const title = document.createElement('div'); title.id = 'desktop-boot-title'; title.style.cssText = 'font-size:22px;font-weight:600';
    const msg = document.createElement('pre'); msg.id = 'desktop-boot-msg';
    msg.style.cssText = 'margin:0;white-space:pre-wrap;max-width:760px;text-align:left;font:13px ui-monospace,Consolas,monospace;opacity:.85';
    el.append(title, msg);
    document.body.append(el);
  }
  return el;
}

/** Resolves with {base, token} when the local backend answers. In a browser it resolves at once
 * with null. The shell restarts a backend that stops, so this is also the way back after one. */
export async function waitForBackend() {
  if (!inTauri) return null;
  const { invoke } = await import('@tauri-apps/api/core');
  const el = overlay();
  const title = el.querySelector('#desktop-boot-title'); const msg = el.querySelector('#desktop-boot-msg');
  title.textContent = 'Starting ShadowTree...';
  msg.textContent = 'Waking up the local helper. This can take up to a minute the first time.';
  for (;;) {
    let s;
    try { s = await invoke('backend_status'); } catch (e) { s = { state: 'error', message: String(e) }; }
    if (s.state === 'ready') { el.remove(); return { base: s.base, token: s.token }; }
    if (s.state === 'error') { title.textContent = 'ShadowTree could not start'; msg.textContent = s.message; return new Promise(() => {}); }
    if (s.message && s.message !== 'Starting ShadowTree...') msg.textContent = s.message;   // e.g. "Restarting it..."
    await sleep(400);
  }
}

/** Native folder picker. Returns a path, or null if the user cancelled. */
export async function pickFolderNative(defaultPath) {
  const { open } = await import('@tauri-apps/plugin-dialog');
  const p = await open({ directory: true, multiple: false, defaultPath: defaultPath || undefined, title: 'Choose a folder to index' });
  return typeof p === 'string' ? p : null;
}

/** Real file-system paths from files dropped on the window. onDrop(path, isOver) */
export async function listenNativeDrop({ onOver, onLeave, onDrop }) {
  if (!inTauri) return;
  const { getCurrentWebview } = await import('@tauri-apps/api/webview');
  await getCurrentWebview().onDragDropEvent((ev) => {
    const p = ev.payload;
    if (p.type === 'over' || p.type === 'enter') onOver();
    else if (p.type === 'leave') onLeave();
    else if (p.type === 'drop') {
      onLeave();
      if (!p.paths?.length) return;
      import('@tauri-apps/api/core').then(({ invoke }) => invoke('drop_folder', { path: p.paths[0] })).then((dir) => { if (dir) onDrop(dir); });
    }
  });
}
