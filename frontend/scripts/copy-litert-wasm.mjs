// Copy the LiteRT.js Wasm runtime from node_modules into public/litert-wasm/ so
// it is served from our own origin. Without this, the Desert Ant SDKs load it
// from the jsDelivr CDN (see @desert-ant-labs/core browserWasmDir()).
// Runs on `npm install` (postinstall) and before dev/build.
import { cpSync, existsSync, mkdirSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const src = fileURLToPath(new URL('../node_modules/@litertjs/core/wasm/', import.meta.url));
const dest = fileURLToPath(new URL('../public/litert-wasm/', import.meta.url));

if (!existsSync(src)) {
  console.error(`[copy-litert-wasm] missing ${src}; run npm install first`);
  process.exit(1);
}
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
console.log(`[copy-litert-wasm] ${readdirSync(dest).length} files -> public/litert-wasm/`);
