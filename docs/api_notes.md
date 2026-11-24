# VeilFS API notes (Phase 0, verified)

Every call later phases make to `cactus`, `gliclass`, `@desert-ant-labs/*` and
`@litertjs/core` must match this file. Everything here was read from the
installed package source and then run on this machine.

Machine: Windows x64 (13th Gen Intel i5-13500HX, 20 logical CPUs, 13.7 GB RAM,
about 3.3 GB free during the runs), Python 3.12.3, Node 24.21.0, npm 10.8.1,
headless Microsoft Edge 158.

## Status

| Capability | Package / call | Status |
|---|---|---|
| Image description | `cactus.Mirage().describe(path)` | ⚠️ works with caveats: no caption field, returns structured JSON |
| Audio transcription | `cactus.transcribe(path)["text"]` | ✅ works, exactly as the spec assumed (16 kHz WAV) |
| Structured extraction | `cactus.extract(text, schema)` / `cactus.Cactus(tools=[...])` (Needle 3) | ⚠️ works with caveats: extractive only, often returns `None` |
| Multi-label folder classification | `gliclass.ZeroShotClassificationPipeline` + `knowledgator/gliclass-v4-edge` | ✅ works on CPU (2.3 GB RAM in float32) |
| Search rerank | same pipeline, query as the only label | ✅ works |
| PII redaction (browser) | `Redact.load()` + `redaction(text)` | ⚠️ works; mandatory license check, see [Desert Ant network calls](#network-calls-and-the-license-check) |
| Topic tags (browser) | `Gist.load()` + `classify(text)` | ⚠️ works; coarse 36-topic taxonomy, license check |
| Emoji suggestion (browser) | `Emo.load()` + `suggestions(text)` | ⚠️ works; license check |
| Desert Ant in a module Web Worker | any of the three | ⚠️ works only with an `importScripts` shim |
| Production build (`vite build` + `vite preview`) | all three | ✅ works |

## Shared setup for the backend (env vars)

Set these **before** `import cactus` / `import gliclass`:

| Variable | Value | Why |
|---|---|---|
| `CACTUS_TELEMETRY` | `0` | `cactus/_telemetry.py` otherwise POSTs usage counts to a Supabase endpoint on `complete/run/extract/transcribe/stream` |
| `DO_NOT_TRACK` | `1` | second Cactus opt-out (same `_enabled()` check) |
| `XDG_CACHE_HOME` | `backend/data/cache` | Cactus engine + `.cact` weights cache (default `~/.cache/cactus`) |
| `HF_HOME` | `backend/data/hf` | Hugging Face cache for Cactus downloads and GLiClass (default `~/.cache/huggingface`) |
| `HF_HUB_DISABLE_TELEMETRY` | `1` | no HF library telemetry |
| `HF_HUB_OFFLINE` | `1` once models are cached | stops all Hub calls, including Cactus `_register_download`, which re-downloads `config.json` on every `fetch_weights()` to count downloads |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | `1` | Windows has no symlinks without Developer Mode; the cache still works (degraded, copies) |

Both spikes set these the same way. Offline reruns with `HF_HUB_OFFLINE=1`
pass (see `docs/review/phase-0.md`).

---

## Cactus Compute (`cactus-compute==4.2.7`, `import cactus`)

Pure-Python wheel (172 KB). On first use it downloads, from Hugging Face at
pinned commits with SHA-256 checks:

| Artifact | HF repo | Size | Cached at (with the env above) |
|---|---|---|---|
| Engine `libcactus.dll` (engine 4.1.4, win_amd64) | `Cactus-Compute/cactus` | 1.9 MB | `backend/data/cache/cactus/engine/4.1.4/<rev>/libcactus.dll` |
| Needle 3 `needle3.cact` | `Cactus-Compute/needle3` | 35.3 MB | `backend/data/cache/cactus/models/needle3/<rev>/` |
| Whistle `whistle.cact` | `Cactus-Compute/whistle` | 16.9 MB | `backend/data/cache/cactus/models/whistle/<rev>/` |
| Mirage `mirage.cact` | `Cactus-Compute/mirage` | 21.6 MB | `backend/data/cache/cactus/models/mirage/<rev>/` |

The HF hub keeps a second copy under `backend/data/hf/hub/` (about 71 MB), so
Cactus uses about 145 MB of disk in total.

Public names (`cactus/__init__.py`): `Cactus`, `Needle` (= `Cactus`), `Whistle`,
`Mirage`, `Field`, `tool`, `extract`, `transcribe`, `stream`, `describe`,
`set_threads`, `ExtractionValidationError`, `__version__`.

Runtime facts that matter for Phase 1:

- One native engine per process. Every call takes the module-level
  `cactus.agent.runtime.lock` (an `RLock`), so calls are serialized across
  threads. Run all Cactus work from the single background job thread.
- Needle, Whistle and Mirage stay loaded together. Interleaving
  text → image → audio → text calls works and gives the same results as
  running each alone (checked: 7 interleaved calls, no reload penalty after the
  first).
- `cactus.set_threads(n)`: CPU threads for models loaded after the call
  (`0` = automatic).
- Errors surface as `RuntimeError` (engine message), `ValueError` (bad
  options) or `cactus.ExtractionValidationError` (strict extraction).

### 1. Image description: `cactus.Mirage`

Spec assumed `cactus.Mirage().describe(path)`. **That call exists**, but it
returns structured JSON, not a caption string.

```python
mirage = cactus.Mirage(weights=None, buffer_size=16 * 1024 * 1024)
result = mirage.describe(image, *, options=None, language=None, keywords=None,
                         width=None, height=None, **settings) -> dict
# one-shot helper that reuses a shared default instance:
result = cactus.describe(image, *, weights=None, **settings) -> dict
mirage.extract(image, form: dict, **settings) -> dict   # constrained form filling
```

- `image`: path (`str`/`PathLike`), encoded image bytes, a Pillow `Image`, a
  `uint8` array shaped `(h, w, 3)`, or packed RGB bytes with `width`/`height`.
  Paths and bytes go through `PIL.Image.open` (read-only) and
  `ImageOps.exif_transpose(...).convert("RGB")`.
- Valid `sections` (checked one by one): `scene`, `objects`, `regions`,
  `text`, `relations`, `events`. **`caption`, `ocr`, `summary`, `tags`,
  `attributes`, `layout` and `description` are rejected** with
  `RuntimeError: invalid options: sections has an unknown name <x>`.
- Other settings named in the Cactus docs: `fields`, `conf`, `text_conf`,
  `max_objects`, `max_text_lines`, `max_tokens`, `mask_format`, `nms`, `form`.
  `fields=["name"]` is rejected; `max_text_lines` and `text_conf` are accepted.
- Default call (no settings) returns every section plus `reasoning`:

```json
{
  "scene": {"background": "white", "style": "screenshot"},
  "objects": [{"id": 1, "name": "text label", "bbox": [21, 37, 347, 103], "score": 0.6,
               "mask": [35, 43, 31, 56, "..."], "position": "center",
               "description": {"color": "black"}}],
  "regions": [{"id": 5, "name": "title bar", "position": "top", "description": {"color": "blue"}}],
  "text": [{"string": "Monthly Budget", "bbox": [14, 22, 354, 118], "score": 0.591},
           {"string": "Groceries $120.50", "bbox": [60, 250, 365, 328], "score": 0.479},
           {"string": "Electricity $64.00", "bbox": [71, 451, 325, 528], "score": 0.636}],
  "relations": [{"subject": 5, "predicate": "part_of", "object": 2}],
  "events": [],
  "reasoning": "lang: en | white and blue window with blue title bar, gray menu, red circle, black text labels | ..."
}
```

- `bbox` values are on a 0-1000 grid, not pixels (the 640x400 test image gave
  y = 451..528 for a line drawn at y = 185 px).
- With `sections=[...]` only those keys come back, and `reasoning` is dropped.
- The text reader is Latin script only (306 characters, per the Cactus docs).
- **Phase 1 plan:** call `describe(image)` with no sections, then build the
  description text from `reasoning` + `scene.style` + region names +
  the `text[].string` lines (OCR). The OCR lines are what make a screenshot
  searchable.

Timing: first `Mirage()` 14.9 s (download + load), cached 0.47 s;
`describe` 1.4-2.0 s for a 640x400 PNG.

### 2. Audio transcription: `cactus.transcribe`

Spec assumed `cactus.transcribe(path)["text"]`. **Correct as written.**

```python
cactus.transcribe(audio, language=None, keywords=None, word_timestamps=False,
                  weights=None) -> dict
whistle = cactus.Whistle(weights=None, buffer_size=1 << 18)
whistle.transcribe(audio, language=None, keywords=None, word_timestamps=False) -> dict
```

- `audio`: a WAV path or 16 kHz mono float samples in [-1, 1]. The WAV reader
  (`cactus/agent/audio.py`) opens the file with `open(path, "rb")`.
- Any rate other than 16 kHz raises `RuntimeError` unless `soxr` is installed
  (`cactus-compute[mic]` extra). Not installed in Phase 0; non-16 kHz WAVs go
  to the fallback path unless we add `soxr` later.
- `language`: one of `en de fr es it nl pl`, or `None` to detect.
- Returns `{"text", "language", "ttft_ms", "decode_tps"}` (+ `"words"` with
  `word_timestamps=True`). Silence returns empty `text`.

Observed: spoken "Please pay the electricity invoice of sixty four dollars
before Friday." → `"Please pay the electricity invoice of $64 before Friday."`,
`language: "en"`. First call 9.1 s (download + load), cached 0.10-0.24 s.

### 3. Structured extraction: Needle 3 (`cactus.extract`, `cactus.Cactus`)

Spec assumed `cactus.Cactus(tools=[...])` and "Needle 3". **Both exist.**
Needle 3 is the default (`generation=3`); `cactus.Needle` is an alias.

```python
agent = cactus.Cactus(tools=None, system=None, weights=None, tool_index_path=None,
                      buffer_size=65536, auto_date=True, generation=None, stateless=False)
agent.complete(text="", max_new_tokens=512, *, audio=None, language=None,
               keywords=None, word_timestamps=False) -> dict
agent.run(query="", max_steps=8, max_new_tokens=512, strict=True) -> dict
agent.reset(); agent.close()   # also a context manager

cactus.extract(text, schema, system=None, max_new_tokens=512, weights=None,
               strict=True, generation=None) -> dict | pydantic model | None
```

- `tools` / `schema`: a raw JSON-schema dict `{"name", "description", "parameters"}`,
  a Pydantic model, or a `@cactus.tool` function.
- `complete()` returns the envelope:

```json
{"type": "call", "success": true, "error": null, "error_code": null, "reason": null,
 "function_calls": [],
 "suppressed_calls": [{"name": "file_card", "arguments": {"title": "INV-2041",
     "summary": "3 ergonomic chairs at $180 each, 1 standing desk at $420",
     "keywords": ["3 ergonomic chairs at $180 each, 1 standing desk at $420"]}}],
 "reasoning": "title 'INV-2041' from query; ...", "confidence": 0.0972,
 "prefill_tps": 574.8, "decode_tps": 268.5, "peak_ram_mb": 276.5,
 "validation": {"ungrounded": [], "negation": false}}
```

  Calls below confidence 0.1 move to `suppressed_calls`. `extract()` reads
  `function_calls` first, then `suppressed_calls`, and returns the first call's
  `arguments` (or `None`).
- `strict=True` can raise `ExtractionValidationError`; use `strict=False` and
  validate the shape ourselves.
- `extract()` caches one agent per `(schema, system, weights, generation)`, and
  `system` gets an automatic `date: YYYY-MM-DD Day HH:MM` prefix, so the cache
  key changes every minute and the agent is rebuilt. For Phase 1, hold one
  `cactus.Cactus(tools=[schema], auto_date=False, stateless=True)` and call
  `complete(text)`, reading `function_calls or suppressed_calls`.

**Behaviour (important):** Needle 3 is a 29-121M parameter tool-calling model.
It copies spans from the input; it does not write summaries. Results on 6
probes with the schema in `spikes/cactus_spike.py`:

| Input | Result |
|---|---|
| invoice | `title "INV-2041"`, `summary` = one copied line, `keywords` = one long span |
| long meeting notes | `title "Search redesign"`, `summary "ship the search redesign by October"`, 4 good keywords |
| receipt | title + copied line, keywords include an email address |
| journal | `None` |
| short meeting notes | `None` |
| `"zzzz qqqq 1234"` | `title "Qqqq"` (junk accepted) |

Adding `minItems`/`maxItems`/`maxLength` constraints made every probe return
`None`, so keep the schema plain. Warm call 0.1-0.8 s; first call 11 s
(download + load).

**Phase 1 plan:** merge per field. Use the AI title only if it is 3-80
characters, the AI summary only if it has at least 20 characters, and split AI
keywords on commas, keeping spans of 1-3 words. Top up missing fields from the
filename / first 300 characters / word-frequency fallbacks. `ai_status = ok`
when at least the title or summary came from the model, else `fallback`.

---

## Knowledgator GLiClass (`gliclass==0.1.22`, model `knowledgator/gliclass-v4-edge`)

- Dependencies pulled in: `torch==2.15.0` (CPU wheel), `transformers==5.24.1`,
  `scikit-learn`, `numpy`, `scipy`.
- Model: 0.4B-parameter DeBERTa-v3-large uni-encoder, Apache-2.0.
  `model.safetensors` is 882 MB (HF cache 849 MiB under
  `backend/data/hf/hub/models--knowledgator--gliclass-v4-edge`).

```python
import torch
from gliclass import GLiClassModel, ZeroShotClassificationPipeline

model = GLiClassModel.from_pretrained("knowledgator/gliclass-v4-edge", dtype=torch.float32).eval()
pipe = ZeroShotClassificationPipeline(
    model, "knowledgator/gliclass-v4-edge",   # 2nd arg: tokenizer or model id
    max_classes=25, max_length=1024, classification_type="multi-label",
    device="cpu",          # the default is "cuda:0", so always pass "cpu"
    progress_bar=False, label_separator=".")

results = pipe(texts, labels, threshold=0.5, batch_size=8, classification_type=None,
               examples=None, prompt=None, return_hierarchical=False)
```

- `model.config.architecture_type` is `"uni-encoder"`.
- transformers 5 takes `dtype=`; `torch_dtype=` is the old name.
- Output: one list per input text. Each list holds
  `{"label": <label text>, "score": float, "initial_score": float}` for labels
  with `score >= threshold` (multi-label, sigmoid). `score` is calibrated;
  `initial_score` is raw. `threshold=0.0` returns every label.
- Labels come back as the exact label strings, so label texts must be unique
  (map them back to folder ids).
- `max_classes=25` is the pipeline's label limit; Phase 1 should batch labels
  in groups of at most 25 if there are more folders.

Observed (labels = four folder descriptions, threshold 0.5):

| Text | Linked folder (score) |
|---|---|
| Invoice INV-2041 ... Total due $960 | Finance & Receipts 0.96 |
| Meeting notes - Q3 roadmap sync ... | Work & Research 0.99 |
| Dear diary, today I walked by the lake ... | Personal & Notes 0.99 |
| Screenshot of a budget app window ... | Screenshots & Media 0.96 |

Rerank (`pipe(passages, [query], prompt="Does the document match the search query?", threshold=0.0)`,
query `"money I spent"`): invoice 43.0%, screenshot 3.5%, journal 3.0%,
meeting 1.5%. Use `score * 100` as the match percentage.

Timing and memory (float32, 10 torch threads): `import torch` 6 s; first load
167 s (882 MB download); cached load 1.1 s + tokenizer 0.8 s;
classification 0.2 s per text with 4 labels; process RSS 2.3 GB.
With `dtype=torch.bfloat16`: RSS 1.4 GB but 1.5 s per text (about 8x slower).
Phase 1 default: float32, with an env override for low-memory machines.

---

## Desert Ant Labs (browser builds) + LiteRT.js

Versions: `@desert-ant-labs/redact@5.0.0`, `@desert-ant-labs/gist@5.0.0`,
`@desert-ant-labs/emo@5.0.0` (each depends on `@desert-ant-labs/core@5.0.0`
and `@bjorn3/browser_wasi_shim@0.3.0`), `@litertjs/core@2.6.0`.
License: Desert Ant Labs Source-Available License (not OSI); LiteRT.js Apache-2.0.

### Imports (browser entries only)

```js
// default entry = ./browser.js (also exported as "./browser"). Never "./native".
const { Redact, DEFAULT_LABELS, ALL_LABELS, DesertAnt } = await import('@desert-ant-labs/redact');
const { Gist } = await import('@desert-ant-labs/gist');
const { Emo } = await import('@desert-ant-labs/emo');
```

Each entry instantiates its ~46 MB wasm core at import time with top-level
await, so use dynamic `import()` after first paint, never a static import.

### Load options (`ModelLoadOptions`, shared)

`Xxx.load({ modelBaseUrl, onProgress, litert, litertWasmDir, accelerator })`

- `litertWasmDir`: where LiteRT.js loads its runtime. **The default is the
  jsDelivr CDN** (`@desert-ant-labs/core` `browserWasmDir()`), so we always pass
  `new URL('/litert-wasm/', location.href).href`.
- `modelBaseUrl`: serve the model files ourselves instead of downloading from
  Hugging Face. Not exercised in Phase 0 (see "Self-hosting" below).
- `onProgress(fraction)`: download progress, 0..1.
- `accelerator`: `"wasm"` (default, XNNPACK CPU), `"webgpu"`, `"webnn"`, `"auto"`.
- `directory`, `cacheRoot`: Node only.

Instance methods on all three: `isDownloaded()`, `dispose()`, `flushTelemetry()`
(waits for license requests), `withCallGroup()` (deprecated, no effect).
`DesertAnt.logLevel` (`"debug" | "info" | "warning" | "error" | "off"`) and
`DesertAnt.logger` control SDK logging.

### Redact

```js
const redact = await Redact.load({ litertWasmDir });
const r = await redact.redaction(text, { minimumConfidence: 0.6, labels: DEFAULT_LABELS });
// r.redactedText: string
// r.items: [{ label, original, placeholder, confidence, start, end }]
// r.restore(textWithPlaceholders): string
```

Labels: `GIVEN_NAME SURNAME STREET_NAME BUILDING_NUMBER SECONDARY_ADDRESS CITY
STATE ZIP_CODE EMAIL PHONE CREDIT_CARD BANK_ACCOUNT ROUTING_NUMBER IP_ADDRESS
URL GOVERNMENT_ID PASSPORT DRIVERS_LICENSE TAX_ID SSN IMEI ORG`.
`DEFAULT_LABELS` = all 21 except `ORG`.

Observed: `"Invoice for Jane Doe, 12 Elm Street, Springfield. Contact billing@example.com or +1 555-0142. Card ending 4242. ..."`
→ `"Invoice for [GIVEN_NAME_1] [SURNAME_1], [BUILDING_NUMBER_1] [STREET_NAME_1], [CITY_1]. Contact [EMAIL_1] or [PHONE_1]. Card ending 4242. ..."`
(7 items, `restore()` round-trips). "Card ending 4242" is not flagged.
Load 7.7-8.9 s (first, with download), call 88-90 ms.

Phase 2 mapping: `has_pii = items.length > 0`,
`pii_types = unique(items.map(i => i.label))`, `redacted_excerpt = redactedText`.

### Gist

```js
const gist = await Gist.load({ litertWasmDir });
await gist.classify(text, { topK: 3, threshold });  // [{ slug, name, score }], top topic always returned; '' -> []
await gist.scores(text);                            // { slug: prob } for all 36 topics
```

Observed on the invoice text: `business` "Business & Entrepreneurship" 0.54,
`technology` "Technology & Software" 0.51 (`finance` only 0.10). The taxonomy is
content/social oriented (e.g. `creator-economy`, `lifestyle-fashion`), so
treat topics as extra tags, not as folders. Load 20-24 s (first, with an 80 MB
download), call 14 ms.

### Emo

```js
const emo = await Emo.load({ litertWasmDir });
await emo.suggestions(text, { limit: 3, skinTone: 'default' });  // [{ emoji, confidence }]; '' -> []
```

Observed: "Finance & Receipts: invoices, receipts, bills and money spent" →
🧾 0.40, 💰 0.30, 📄 0.12. "Travel plans: flights, hotels and trips" → ✈ 0.47,
🏨 0.25, 🗺 0.08. "Personal & Notes: journal and private notes" → 📓 0.27, 📝 0.22, 🗒 0.13.
Load 3.2-4.3 s (first), about 5 ms per call.

### Network calls and the license check

Captured with Chrome DevTools Protocol `Network.requestWillBeSent` on page and
worker targets (`frontend/spikes/run-browser-spike.mjs`). With
`litertWasmDir` set, nothing goes to jsDelivr. Requests that left 127.0.0.1:

| Host | Requests | Purpose |
|---|---|---|
| `huggingface.co` | `GET /api/models/desert-ant-labs/<m>/tree/<tag>`, `GET /desert-ant-labs/<m>/resolve/<tag>/<file>` | model download at pinned tags |
| `us.aws.cdn.hf.co` | `GET /xet-bridge-us/...` | HF file CDN |
| `events.desertant.com` | `POST /api/v1/license`, `POST /api/v1/activate` (+ CORS `OPTIONS`), from page **and** worker | Desert Ant **License Check** |

Pinned model tags requested by the SDK and files fetched:

| Model | Tag (commit) | Files |
|---|---|---|
| redact | `v0.4.2` (`8fdd43be...`) | `redact.tflite` 23.9 MB, `redact_tokenizer.bin` 0.4 MB, `labels.json` |
| gist | `v2.2.0` (`c2f5d5a5...`) | `gist.tflite` 13.0 MB, `gist_embedding.i8` 66.9 MB, `gist_tokenizer.bin` 4.6 MB, `gist_embedding.json`, `gist_config.json`, `taxonomy.json` |
| emo | `v0.7.0` (`217ba547...`) | `emo.tflite` 10.2 MB, `emo_tokenizer.bin` 0.7 MB, `emo_meta.json` |

`redact.isDownloaded()` reports `false` right after a successful load (the
browser build has no persistent cache root), so expect a re-download per page
load unless the files are self-hosted.

**License Check.** The wasm cores contain `https://events.desertant.com/api/v1`
and `LicenseGrantRequest` / `LicenseActivateRequest` types. The license text at
https://license.desertant.com (v1.1, 30 Oct 2026) says the check sends a random
install ID, the site domain, the model and version, the SDK name and version,
and the platform, never inputs or outputs. It has **no opt-out**, and the
license **forbids disabling, blocking or spoofing it** (Section 6). If the check
fails, the model keeps running. Air-gapped products need a signed offline
license from licensing@desertant.com. The SDK reads `globalThis.__dalLicenseEndpoint`
(the package's own tests point it at `127.0.0.1:9`), but using that to dodge
the check would breach the license, so VeilFS must not.

This conflicts with the non-negotiable "no telemetry". It is the open decision
in `docs/review/phase-0.md`.

The license also requires a visible "Powered by Desert Ant Labs" credit linked
to https://desertant.com (Section 9).

### Vite configuration (verified in dev and in `vite build` + `vite preview`)

All in `frontend/vite.config.js` and `frontend/package.json`:

1. `optimizeDeps.exclude: ['@desert-ant-labs/redact', '@desert-ant-labs/gist',
   '@desert-ant-labs/emo', '@desert-ant-labs/core', '@litertjs/core']`.
   The entries load their core with `new URL("XxxWeb.wasm", import.meta.url)`;
   pre-bundling would break that relative URL.
2. `build.target: 'esnext'`, because the entries use top-level await.
3. LiteRT.js runtime copied to `public/litert-wasm/` by
   `scripts/copy-litert-wasm.mjs` (`postinstall`, `predev`, `prebuild`), and
   passed as `litertWasmDir`. The folder is gitignored (8 files, about 46 MB).
4. **No `assetsInclude` needed**: Vite emits the three cores from the
   `new URL(...)` pattern as `dist/assets/{Redact,Gist,Emo}Web-<hash>.wasm`
   (46.3-46.5 MB each, about 19.4 MB gzip).
5. **No COOP/COEP needed**: the SDK calls `loadLiteRt(dir)` without
   `threads`, so LiteRT picks `litert_wasm_internal.js` (relaxed SIMD,
   single-threaded). The page ran with `crossOriginIsolated === false`.
6. `server.host` / `preview.host` are `127.0.0.1` (ports 5173 / 4173, strict).
7. `worker.format: 'es'`.

### Web Worker

- A module worker (`new Worker(url, { type: 'module' })`) **fails** without help:
  `TypeError: Module scripts don't support importScripts()`, thrown from
  `@litertjs/wasm-utils` `runScript()`, which calls `importScripts` whenever
  that function exists.
- **Fix (verified in dev and build):** before importing a Desert Ant package in
  the worker, install a shim (`frontend/spikes/spike-worker.js`):
  `self.importScripts` does a synchronous `XMLHttpRequest` (allowed in workers)
  and evaluates the script in global scope (`(0, eval)(text)`), and
  `self.Module = { locateFile: p => new URL(p, litertWasmDir).href }` points the
  Emscripten glue at `/litert-wasm/`. Emo then loads in 3.7-4.4 s and answers
  in the worker.
- Consequence: a future Content-Security-Policy must allow `'unsafe-eval'` for
  the worker script.

### Self-hosting the models (Phase 2 task, not yet verified)

To avoid the Hugging Face download on every page load, download the files in
the table above once into `frontend/public/models/<model>/` (gitignored) and
pass `modelBaseUrl: '/models/<model>/'`. The SDK then fetches
`<artifact>` + `<sidecars>` as reported by the core's own `modelInfo()`.
Whether that list matches the files above exactly still has to be checked in
Phase 2; if self-hosting fails, keep the HF download as the fallback.
