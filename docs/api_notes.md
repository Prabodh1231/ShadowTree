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
| Image description | `cactus.Mirage().describe(path)` | âš ï¸ works with caveats: no caption field, returns structured JSON |
| Audio transcription | `cactus.transcribe(path)["text"]` | âœ… works, exactly as the spec assumed (16 kHz WAV) |
| Structured extraction | `cactus.extract(text, schema)` / `cactus.Cactus(tools=[...])` (Needle 3) | âš ï¸ works with caveats: extractive only, often returns `None` |
| Multi-label folder classification | `gliclass.ZeroShotClassificationPipeline` + `knowledgator/gliclass-v4-edge` (removed in Step 1, now DeBERTa) | âœ… works on CPU (2.3 GB RAM in float32) |
| Search rerank | same pipeline, query as the only label (removed in Step 1, now FlashRank) | âœ… works |
| PII redaction (browser) | `Redact.load()` + `redaction(text)` | âš ï¸ works; mandatory license check, see [Desert Ant network calls](#network-calls-and-the-license-check) |
| Topic tags (browser) | `Gist.load()` + `classify(text)` | âš ï¸ works; coarse 36-topic taxonomy, license check |
| Emoji suggestion (browser) | `Emo.load()` + `suggestions(text)` | âš ï¸ works; license check |
| Desert Ant in a module Web Worker | any of the three | âš ï¸ works only with an `importScripts` shim. **Decision: run on the main thread, no worker** |
| Production build (`vite build` + `vite preview`) | all three | âœ… works |

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
  text â†’ image â†’ audio â†’ text calls works and gives the same results as
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
before Friday." â†’ `"Please pay the electricity invoice of $64 before Friday."`,
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
It copies spans from the input; it does not write summaries. Results with the
plain schema in `spikes/cactus_spike.py`:

| Input | Result |
|---|---|
| invoice | `title "INV-2041"`, `summary` = one copied line, `keywords` = one long span |
| long meeting notes | `title "Search redesign"`, `summary "ship the search redesign by October"`, 4 good keywords |
| receipt | title + copied line, keywords include an email address |
| journal (long) | `None` |
| journal (short, in the spike) | `title "Painting"`, `summary "start painting again"`, `keywords ["painting"]` |
| short meeting notes | `None` |
| `"zzzz qqqq 1234"` | `title "Qqqq"` (junk accepted) |

The invoice call scored confidence 0.05-0.10 across runs, so it arrived in
`suppressed_calls`; results are stable per input but the score is not.

Adding `minItems`/`maxItems`/`maxLength` constraints made every probe return
`None`, so keep the schema plain. Warm call 0.1-0.8 s; first call 11 s
(download + load). Probes: 3 in the spike, 6 in a one-off scratch script.

**Phase 1 plan:** merge per field. Use the AI title only if it is 3-80
characters, the AI summary only if it has at least 20 characters, and split AI
keywords on commas, keeping spans of 1-3 words. Top up missing fields from the
filename / first 300 characters / word-frequency fallbacks. `ai_status = ok`
when at least the title or summary came from the model, else `fallback`.

---

## Knowledgator GLiClass (`gliclass==0.1.22`, model `knowledgator/gliclass-v4-edge`) (REMOVED in Step 1)

> Removed: GLiClass, torch and transformers are gone from the code and the venv. Kept below as the Phase 0 record. The replacement is in [ShadowTree model stack](#shadowtree-model-stack-step-1-verified).


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

## ShadowTree model stack (Step 1, verified)

All calls below ran for real in `spikes/shadowtree_spike.py` (Windows x64, Python 3.12.3, offline, 25 Nov 2026) after `scripts/download_models.py`. Replaces GLiClass. No torch, transformers or scikit-learn in the venv (414 MB).

Pinned in `backend/requirements.txt`: `onnxruntime==1.32.0`, `tokenizers==0.23.3`, `model2vec==0.10.0`, `FlashRank==0.2.10`, `rapidocr==3.10.0`, `pypdfium2==5.15.2`, plus rapidocr's deps `opencv-python-headless==5.1.0.95`, `pyclipper==1.4.0`, `shapely==2.2.0`, `omegaconf==2.4.0`, `six`, `colorlog`, `requests`. `pip check`: clean. `safetensors` and `joblib` stay (model2vec needs them).

### Where files live (`backend/data/models/`, set by `config.model_dir(name)`)

| Folder | Files | Size |
|---|---|---|
| `deberta/` | `onnx/model_quantized.onnx` (87.25 MB), `tokenizer.json` (8.66 MB), `config.json` | 95.9 MB |
| `potion-base-8M/` | `model.safetensors` (30.24 MB), `tokenizer.json` (0.68 MB), `config.json` | 30.9 MB |
| `flashrank/ms-marco-TinyBERT-L-2-v2/` | `flashrank-TinyBERT-L-2-v2.onnx` (4.49 MB), `tokenizer.json`, `config.json`, 2 small json | 5.0 MB (the zip is unpacked with a `__MACOSX/` folder of empty stubs, ignore it) |
| `ocr/` | `ch_PP-OCRv5_det_mobile.onnx` (4.82 MB), `ch_PP-OCRv5_rec_mobile.onnx` (16.63 MB), `ppocrv5_dict.txt` (0.07 MB) | 21.5 MB |

Total new download: about 153 MB. Hosts: huggingface.co (DeBERTa, potion, FlashRank zip at `huggingface.co/prithivida/flashrank`) and modelscope.cn (OCR, SHA256 checked in `download_models.py`). Nothing is fetched at runtime: `HF_HUB_OFFLINE=1`, and `ai_classify.model_files_present()` checks the folders on disk (the `/health` `classifier.files_present` block).

### DeBERTa NLI: `onnxruntime` + `tokenizers`

```python
import onnxruntime as ort
from tokenizers import Tokenizer
so = ort.SessionOptions(); so.intra_op_num_threads = get_settings().onnx_threads   # env ONNX_THREADS, default cores // 2
sess = ort.InferenceSession(".../onnx/model_quantized.onnx", so, providers=["CPUExecutionProvider"])
tok = Tokenizer.from_file(".../tokenizer.json")
tok.enable_truncation(max_length=384, strategy="only_first")        # truncate the premise only
tok.enable_padding(pad_id=tok.token_to_id("[PAD]") or 0, pad_token="[PAD]")
enc = tok.encode_batch([(premise, hypothesis), ...])                 # pair: [CLS] premise [SEP] hypothesis [SEP]
logits = sess.run(None, {"input_ids": int64 (n, L), "attention_mask": int64 (n, L)})[0]   # (n, 2) float32
```

- Graph inputs: `input_ids`, `attention_mask` only (both `int64`, shape `[batch_size, sequence_length]`). No `token_type_ids`. Output: `logits` `[batch_size, 2]`.
- `config.json` `id2label` = `{"0": "entailment", "1": "not_entailment"}`: entailment is index 0. Read it from the file, do not hard-code. `max_position_embeddings` 512.
- Score = `softmax(logits, axis=-1)[:, entailment_index]`.
- Pair encoding confirmed: tokens start `[CLS] ▁Corner ▁Cafe ...`; `type_ids` are 0 for the premise (the model ignores them).
- Load (session + tokenizer): 0.7 s. Run 2 pairs of about 60 tokens: 0.04 s. Spike result: coffee receipt text vs "This text is about receipts and payments." = 0.996 entailment; vs "...a personal diary." = 0.001.

### potion: `model2vec`

```python
from model2vec import StaticModel
m = StaticModel.from_pretrained(r"...\data\models\potion-base-8M")   # local folder, no network
v = m.encode(["text", ...])        # np.ndarray (n, 256) float32
```

`from_pretrained(path, token=None, normalize=None, subfolder=None, quantize_to=None, dimensionality=None, vocabulary_quantization=None, max_length=<unset>, force_download=True)`. `encode(sentences, *, show_progress_bar=False, max_length=<unset>, normalize=None, batch_size=1024, use_multiprocessing=True, ...)`. Vectors are not unit length: normalise before cosine. Load 0.34 s, encode 3 short texts under 5 ms. Spike cosines: "money I spent" vs "coffee receipt total" 0.18, vs "walk by the lake" 0.00.

### FlashRank

```python
from flashrank import Ranker, RerankRequest
rk = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir=r"...\data\models\flashrank", log_level="WARNING")
res = rk.rerank(RerankRequest(query="...", passages=[{"id": 0, "text": "..."}, ...]))
# list of dicts {"id", "text", "score"} sorted by score, best first (score is a float in 0..1)
```

- Signatures: `Ranker(model_name='ms-marco-TinyBERT-L-2-v2', cache_dir='/tmp', max_length=512, log_level='INFO')`; `RerankRequest(query=None, passages=None)`.
- `Ranker.__init__` downloads the zip from huggingface.co if `cache_dir/<model>` is missing, so the backend must check the folder first (Step 2). `log_level="WARNING"` stops its `logging.basicConfig` from chattering.
- Load 0.05 s. Spike scores for query "money I spent": coffee receipt 0.0001, invoice 0.0000, diary 0.0000. So raw scores are tiny and `match = score * 100` will not work for this query; Step 2 must rescale (rank-based or sigmoid on the logit) and re-tune `MIN_MATCH` and `TOP_FLOOR`.

### RapidOCR (PP-OCRv5 mobile, explicit model paths)

```python
from rapidocr import ModelType, OCRVersion, RapidOCR
eng = RapidOCR(params={
    "Det.model_path": ".../ch_PP-OCRv5_det_mobile.onnx", "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
    "Rec.model_path": ".../ch_PP-OCRv5_rec_mobile.onnx", "Rec.rec_keys_path": ".../ppocrv5_dict.txt",
    "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
    "Global.log_level": "warning", "EngineConfig.onnxruntime.intra_op_num_threads": 2})
out = eng(png_bytes_or_ndarray_or_path)    # RapidOCROutput
out.txts     # tuple[str], one per line, top to bottom (None when nothing found)
out.scores   # tuple[float]
```

- `RapidOCR(config_path=None, params=None)`. Keys are dotted `Section.key`; `ocr_version`, `model_type`, `engine_type`, `task_type` must be the Enum, not a string (a string raises `TypeError: ... must be Enum Type`). Unknown keys raise `ValueError`.
- The wheel ships PP-OCRv6 small models (det 9.9 MB, rec 21 MB) and uses them by default. Passing `*.model_path` selects the v5 files, so nothing is downloaded at runtime. The onnx rec model carries its own character list; `rec_keys_path` is accepted and harmless.
- Model choice (owner named PP-OCRv5 mobile): tested `en_PP-OCRv5_rec_mobile` (7.9 MB) and `ch_PP-OCRv5_rec_mobile` (16.6 MB) on the sample screenshot. English read "Error code Ox80070005" (letter O). Multilingual `ch` read "0x80070005" correctly and also reads English, so the `ch` rec model is the one used. The English files were deleted again.
- Screenshot result (`Screenshot 2026-11-20.png`): `Error | Payment failed | Could not save your invoice. | Error code 0x80070005: access denied. | Retry`, scores 0.94 to 1.0. First call (includes lazy session load) 0.8 to 1.0 s.
- Fallback if the ModelScope download ever fails: omit `*.model_path` and the bundled PP-OCRv6 small models run. Not needed in this run (download and SHA256 passed).

### pypdfium2

```python
import io, pypdfium2 as pdfium
pdf = pdfium.PdfDocument(io.BytesIO(data))     # data = open(path, "rb").read(): keeps the read-only rule literal
page = pdf[0]; img = page.render(scale=200/72).to_pil()    # PIL image, in memory, nothing written
pdf.close()
```

`PdfDocument(input, password=None, autoclose=False)`. `len(pdf)` is the page count. Invoice sample page 1 at 200 dpi: 1654 x 2339 px in 0.04 s. RapidOCR on that array (BGR `np.ndarray`) read the invoice lines correctly ("Invoice 2041", "From: Northwind Supplies...", the line items). Cap pages and pixel size before rendering (Step 4).

### Seams kept at this commit

`ai_classify.classify(text, labels)` and `ai_classify.rerank(query, passages)` raise `ai_classify.NotReady` until Steps 3 and 2. New seams `ai_embed.embed(texts)` and `ai_ocr.ocr_image(bytes)` raise it too. Tests monkeypatch all four by name.

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
â†’ `"Invoice for [GIVEN_NAME_1] [SURNAME_1], [BUILDING_NUMBER_1] [STREET_NAME_1], [CITY_1]. Contact [EMAIL_1] or [PHONE_1]. Card ending 4242. ..."`
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

Observed: "Finance & Receipts: invoices, receipts, bills and money spent" â†’
ðŸ§¾ 0.40, ðŸ’° 0.30, ðŸ“„ 0.12. "Travel plans: flights, hotels and trips" â†’ âœˆ 0.47,
ðŸ¨ 0.25, ðŸ—º 0.08. "Personal & Notes: journal and private notes" â†’ ðŸ““ 0.27, ðŸ“ 0.22, ðŸ—’ 0.13.
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

**Decision: Option A, chosen by the owner.** Allow the check and disclose it
(README "Network & privacy"). The steering rule now reads "No user content
leaves the machine" and names the license check as an allowed outbound request
(`.kiro/steering/non-negotiables.md`). License versions: the npm packages
`@desert-ant-labs/*@5.0.0` ship `LICENSE.md` v1.0, which points to
https://license.desertant.com/1.0. The site is at v1.1 (30 October 2026). v1.1
describes the license check this SDK actually makes, so VeilFS relies on v1.1.

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

**Decision (Phase 0 review): run Desert Ant on the main thread after first
paint via dynamic `import()`. No worker shim (the shim stays only as spike
evidence in `frontend/spikes/spike-worker.js`). Revisit only if Phase 2 shows
UI jank.** What follows is the spike evidence.

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

### Self-hosting the models (verified in Phase 2)

`frontend/scripts/fetch-browser-models.mjs` (`npm run fetch-models`) downloads
the files below once into `frontend/public/models/<model>/` (gitignored, 114 MB,
sizes and LFS sha256 checked against the Hub listing at the pinned tag; a second
run skips files whose size matches). `browserAI.js` sends a HEAD request for
`/models/<m>/<m>.tflite` and passes `modelBaseUrl: '/models/<m>/'` when it
answers with a non-HTML 200, else it uses the default Hugging Face download.

Result: with the files present, `Redact.load`, `Gist.load` and `Emo.load` with
`modelBaseUrl` all worked (headless Edge, `vite preview`). Total load of the
three: 3.9 s. **No request went to huggingface.co or the HF CDN.** The only
requests that left 127.0.0.1 were the license check
(`POST/OPTIONS events.desertant.com/api/v1/license` and `/activate`).

File list source: `modelInfo()` is internal to the wasm core and not exported,
so the list is the Phase 0 table of requested files (checked against
`GET huggingface.co/api/models/desert-ant-labs/<m>/tree/<tag>`), plus
`labels.json` and `redact_meta.json` for redact. The load working proves the
list is enough; extra small JSON files may not be needed.

| Model | Tag | Files (bytes) |
|---|---|---|
| redact | `v0.4.2` | `redact.tflite` 23929696, `redact_tokenizer.bin` 391416, `labels.json` 3842, `redact_meta.json` 752 |
| gist | `v2.2.0` | `gist.tflite` 13034484, `gist_embedding.i8` 66905344, `gist_tokenizer.bin` 4625812, `gist_embedding.json` 67, `gist_config.json` 823, `taxonomy.json` 8018 |
| emo | `v0.7.0` | `emo.tflite` 10222736, `emo_tokenizer.bin` 733197, `emo_meta.json` 6280 |

Deviations from the Phase 0 notes: none in the API. `vite preview` answers
unknown paths with `index.html` (HTTP 200), so the self-host check must also
reject `text/html`. `vite build` copies `public/models/` into `dist/` (114 MB;
the whole build was 292 MB).