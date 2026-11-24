# Phase 0: reviewer feedback

**Verdict: approved. Proceed to Phase 1** with the decisions and notes below.

I re-ran both backend spikes offline (`HF_HUB_OFFLINE=1`). The results match the review note: Mirage 1.5 s, Whistle gave the exact transcript, Needle gave `INV-2041` and `None`-prone output, GLiClass gave the same four folders and 43.0% for "money I spent". I also confirmed that the Cactus telemetry opt-out (`CACTUS_TELEMETRY=0`, `DO_NOT_TRACK`) exists in `cactus/_telemetry.py`, and that `backend/data/`, `dist/`, `public/litert-wasm/`, `.venv/` and `node_modules/` are all gitignored. Nothing large is tracked.

## Decisions

1. **Desert Ant license check: Option A (confirmed by the project owner).** Allow the check. Do not block, spoof, or redirect `__dalLicenseEndpoint`. Update the steering rule from "no telemetry" to:
   > **No user content leaves the machine.** File contents, text, summaries, and results are never sent anywhere. The only outbound requests are (a) first-run model downloads and (b) the Desert Ant license check (install ID, domain, model and SDK version, platform; no content). Both are disclosed in the README.
   
   Then:
   - add a "Powered by Desert Ant Labs" credit linked to https://desertant.com in the sidebar footer
   - add a short "Network & privacy" section to the README that lists exactly these requests
   - note that the npm package ships `LICENSE.md` v1.0, while the site is at v1.1. Cite the version you rely on.
2. **No Web Worker shim. Run Desert Ant on the main thread** after first paint, via dynamic `import()`. Calls take 5–90 ms, and the shim adds `eval` plus sync XHR, which we don't need. Only go back to a worker if Phase 2 shows real UI jank, and record it if you do.
3. **Self-host the browser models** (`modelBaseUrl`) in Phase 2. Add a `scripts/fetch-browser-models.mjs` that downloads the pinned files into `frontend/public/models/` (gitignored). Keep HF download as the fallback.
4. **Move `KIRO_PROMPT.md` to `docs/spec.md`** and commit it.

## Phase 1 notes

1. **Offline by default.** Add `scripts/download_models.py`, which downloads every backend model once into `backend/data/`. The backend then always starts with `HF_HUB_OFFLINE=1`, `CACTUS_TELEMETRY=0`, `DO_NOT_TRACK=1`, and the cache env vars set in `config.py`, **before** importing `cactus` or `gliclass`. `/health` reports clearly if models are missing ("run download_models.py").
2. **Needle 3 is weak, so plan the demo around it.** Your per-field merge plan is good. Also:
   - Summary fallback: choose the first one or two *meaningful* sentences (skip headers, lines under 20 chars, lines that are only numbers or dates), not just the first 300 chars.
   - Keywords: split long copied spans, drop stopwords and numbers, then top up from word frequency. Max 6.
   - **15-minute experiment** (optional): try separate single-field tools (`get_title`, `get_keywords`) to see whether Needle returns `None` less often than with the combined schema. Keep it only if it clearly helps. Record the result either way.
3. **Mirage description cleanup.** On the spike image, `reasoning` said "cannot read the text labels" even though `text` returned all three OCR lines. Build the description mainly from OCR lines plus `scene.style` plus region names, and drop reasoning fragments that contain "cannot read" or "unclear".
4. **Search match % looks weak in a demo.** The best hit for "money I spent" is 43%. Return both `score` (raw GLiClass) and a `match` that blends a normalized BM25 rank with the GLiClass score, or scale relative to the top hit. Document the formula. The UI should never show "43% match" next to an obviously perfect result.
5. **Memory.** GLiClass needs 2.3 GB RSS in float32 and this machine had about 3.3 GB free. Load the model **once, lazily on the first job**, never per request, and keep it out of Uvicorn reload workers (don't use `--reload` in the documented run command, or guard it). Keep the `GLICLASS_DTYPE=bfloat16` override and document it.
6. **Cactus is single-engine and serialized.** All Cactus and GLiClass work runs on the one job thread. Request handlers never call models directly, except `/search`'s rerank. That one goes through the same lock or queue so it can't collide with a running scan.
7. **Audio.** Add `soxr` (or `cactus-compute[mic]`) if it installs cleanly on Windows, so non-16 kHz WAVs work. Otherwise they take the fallback with a clear `ai_error`. Call `transcribe` with `language=None` (auto-detect).
8. **Spike leftovers.** Keep `spikes/` in the repo (it's good evidence for judges), but the Phase 1 app must not import from it. In the Phase 3 sample generator, don't interpolate paths into a single-quoted PowerShell string. Pass the path as an argument (e.g. `-Command` with `$args[0]`), or a path with an apostrophe breaks.

## Look-ahead (Phase 3 demo mode)

The three wasm cores are about 46 MB each (about 140 MB total), plus about 120 MB of models. For the GitHub Pages demo build, **don't load Desert Ant at all**: ship precomputed `client_meta` (PII flags, redacted excerpts, topics) and emojis inside `snapshot.json`. Show a note that live privacy scanning runs in the local app.
