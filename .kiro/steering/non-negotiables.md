---
inclusion: always
---

# ShadowTree non-negotiables

Every task in this repo must follow these rules. They outrank convenience.

- **Read-only on user data.** Scanned files are opened only with `open(path, "rb")` or equivalent read-only APIs. Nothing is ever written inside the scanned root: no DB, cache, thumbnails, or temp files there. App data lives in `backend/data/`.
- **No invented APIs.** Every call to `cactus`, `onnxruntime`, `tokenizers`, `model2vec`, `flashrank`, `rapidocr`, `pypdfium2`, `@desert-ant-labs/*`, and `@litertjs/core` must match what Phase 0 verified in `docs/api_notes.md`. If a method from this spec doesn't exist, use the real equivalent and record the deviation. Never guess.
- **Every AI step has a fallback.** If a model errors, times out, or returns empty, the file is still indexed. The fallbacks are a title from the filename, a summary from the first ~300 chars of text or basic metadata, and keywords from simple frequency analysis. Record `ai_status` per file (`ok | fallback | error`) and show it subtly in the UI.
- **Local only.** The backend binds to `127.0.0.1`. CORS allows only the Vite dev origin and the built frontend origin. There are no cloud AI APIs.
- **No user content leaves the machine.** File contents, text, summaries, and results are never sent anywhere. The only outbound requests are (a) first-run model downloads (huggingface.co and its CDN, modelscope.cn) and (b) the Desert Ant license check (install ID, domain, model and SDK version, platform; no content). Both are disclosed in the README.
- **No secrets or personal data in the repo.** Sample data uses obviously fake values (`@example.com` emails, `555-01xx` phone numbers).
- **Windows first.** Commands in the README are PowerShell. Paths go through `pathlib`. Handle spaces in paths.
