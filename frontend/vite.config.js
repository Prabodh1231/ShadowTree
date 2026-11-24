import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

// The Desert Ant browser builds load their own .wasm core with
// `new URL("XxxWeb.wasm", import.meta.url)` and use top-level await, and
// @litertjs/core loads its runtime from a directory at run time. Pre-bundling
// them into node_modules/.vite/deps breaks those relative URLs, so they are
// excluded from dependency optimization and served as-is.
const BROWSER_AI = [
  '@desert-ant-labs/redact',
  '@desert-ant-labs/gist',
  '@desert-ant-labs/emo',
  '@desert-ant-labs/core',
  '@litertjs/core',
];

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
  optimizeDeps: {
    exclude: BROWSER_AI,
  },
  // Top-level await in the Desert Ant entries needs an esnext target.
  build: {
    target: 'esnext',
    rollupOptions: {
      input: {
        spike: here('./spikes/browser-spike.html'),
      },
    },
  },
  worker: {
    format: 'es',
  },
});
