// Phase 0 probe: can a Desert Ant model run inside a module Web Worker?
//
// LiteRT.js (@litertjs/wasm-utils runScript) loads its Emscripten glue with
// importScripts() when that function exists, and module workers throw on
// importScripts(). Module workers do allow synchronous XHR, so the shim below
// fetches the classic glue script and evaluates it in global scope, which is
// what importScripts would have done. Module.locateFile points the glue at
// /litert-wasm/ for its .wasm file (otherwise it resolves next to this worker).
function installImportScriptsShim(wasmDir) {
  self.importScripts = (...urls) => {
    for (const url of urls) {
      const xhr = new XMLHttpRequest();
      xhr.open('GET', String(url), false);
      xhr.send();
      if (xhr.status !== 200) throw new Error(`importScripts shim: ${url} -> HTTP ${xhr.status}`);
      (0, eval)(`${xhr.responseText}\n//# sourceURL=${url}`);
    }
  };
  self.Module = { locateFile: (path) => new URL(path, wasmDir).href };
}

self.onmessage = async (e) => {
  const t0 = performance.now();
  try {
    if (e.data.shim) installImportScriptsShim(e.data.litertWasmDir);
    const { Emo } = await import('@desert-ant-labs/emo');
    const emo = await Emo.load({ litertWasmDir: e.data.litertWasmDir });
    const loadMs = Math.round(performance.now() - t0);
    const suggestions = await emo.suggestions(e.data.text, { limit: 3 });
    self.postMessage({ ok: true, shim: Boolean(e.data.shim), loadMs, text: e.data.text, suggestions });
  } catch (err) {
    self.postMessage({ ok: false, error: String(err?.stack || err) });
  }
};
