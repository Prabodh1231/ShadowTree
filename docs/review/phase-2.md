# Phase 2 review note: Frontend and browser AI

Status: Step 1 of this note (Phase 1 fixes, UI, browser AI, backend). The wiring fixes and the real-model screenshots are added in a later section when done. Nothing is pushed. Everything is on local `main`.

## Phase 1 review fixes (owner list, `docs/review/phase-1-feedback.md`)

Backend tests are in `backend/tests/test_review_fixes.py` unless noted.

| ID | What changed | Commit | Test |
|---|---|---|---|
| (feedback) | Reviewer feedback file added | 5003c15 | none |
| C1 | `sha256` on `/files` cards. `PATCH /files/{id}/client-meta` requires `sha256`, checks it, returns 409 on mismatch, stores it in `client_meta` | 0c20307 | `test_c1_cards_have_sha256_and_patch_checks_it`, `test_api.py::test_sensitive_counts_and_client_meta` (updated) |
| L4 (MUST) | `POST /folders` scores against all labels, writes only the new folder's links, drops Unsorted only for files that gain a link. `scanner.link_new_folders` replaces `reclassify_all` | b0b2db5 | `test_l4_new_folder_keeps_existing_links` |
| L1 (MUST) | Cut-off 35, `weak` list (top 3, `[]` when results exist), +20 name/title boost, 40 FTS + 20 recent candidates, batches of 16 with the model lock released between batches | bf729e6 | `test_l1_name_boost_rules`, `test_l1_cutoff_weak_and_shape`, `test_l1_invoice_name_boost_ranks_it_first`, `test_l1_candidates_capped_and_batched` |
| L2 (MUST) | Model title or summary kept only if at least 90% of its tokens (lowercase, length over 2) are in the source text. Else fallback, provenance `summary:fallback(ungrounded)` or `title:fallback(ungrounded)` | 3a69899 | `test_l2_is_grounded_digitale_migration`, `test_l2_build_card_uses_fallback_for_ungrounded_summary` |
| N3 (MUST) | Folders that failed to list or stat are tracked. The "removed" step skips DB paths inside them | 13fa41d | `test_n3_unreadable_folder_keeps_its_rows` (monkeypatched `os.scandir`) |
| S1 | `skipped_too_large`, `skipped_cloud_only`, `skipped_hidden_or_link` always in scan stats as ints. Cloud-only means attribute `0x400000` or `0x1000` only | 6887240 | `test_s1_skip_counts_with_fake_attributes`, `test_s1_keys_present_without_skips` |
| N2 | `scan_root` is written only after `start_scan` succeeds | 1cc6deb | `test_n2_refused_scan_does_not_change_scan_root` |
| L3 | `ai_error` is one line, at most 200 chars, cut text ends in an ellipsis, provenance suffix kept | 04a8d1a | `test_l3_ai_error_is_one_short_line` |
| L5 | Status `ok` keeps only provenance in `ai_error`. Side notes become `note:...` tokens | 04a8d1a | `test_l5_ok_status_has_only_provenance` |
| L6 / N10 | `/health` `files_present` is `{"<model>": bool}` on both stacks. Cactus models need the weights and `libcactus.dll`. Dead `or "whistle" in loaded` clause removed | 9718ff0 | `test_l6_files_present_shape_on_both_stacks`, `test_n10_cactus_needs_the_engine_dll` |
| N5 | Any Whistle load error is cached (Mirage already cached any load error) | a926ab6 | `test_n5_whistle_load_error_is_cached` |
| N7 | Test asserts the full `["explorer", "/select,", path]` list | 1be9497 | `test_api.py::test_reveal_rejects_unknown_and_paths` |
| N11 | `_ONLY_NUM_DATE` uses `\u20ac\u00a3` escapes. The file had no stray `?`; it was a console encoding artefact, the escapes make it encoding-proof | 1be9497 | `test_n11_numeric_lines_with_currency_symbols_are_skipped` |
| C-2 | Cut summaries end in an ellipsis (`extractors.cut_text`) | 1be9497 | `test_c2_cut_summary_ends_with_ellipsis` |
| L8 | README: foreground uvicorn, stop with Ctrl+C, no `Start-Process`. Added `cd frontend; npm run fetch-models` line (about 114 MB). Network and privacy row 2 updated | 4e729d4 | docs only |
| Spec lines | "No telemetry" line now matches the steering rule. Phase 3 smoke test now says top 3 Finance for "money I spent" and the invoice first for "invoice" | 4e729d4 | docs only |

Not fixed, as the owner said: N8, L7, C-3, C-7, the rest of N12.

## What was built in Phase 2

By spec feature (UI commits a7889fa, 24179a5, 93e6963):

1. **Shell.** Sidebar (All Files, Sensitive (PII), Unsorted, default and custom folders with emoji and count, New Virtual Folder with optional description). Top bar with path input, Index (Read-Only), progress bar from `/scan/status`, search. "Read-only" badge. Desert Ant credit in the sidebar footer (`target=_blank`, `rel="noopener noreferrer"`).
2. **Cards.** Kind icon, title, summary, topic and keyword tags, folder chips with match %, PII badge, path with Copy, Reveal on Disk (`POST /reveal`), `ai_status` dot with tooltip.
3. **Search.** Results grid. Reads both the old plain array and the new `{results, weak}` shape. Empty results plus `weak` shows "No strong matches. Closest:".
4. **Drawer.** Redacted / Original toggle, Redacted by default. No redacted excerpt shows "Privacy scan pending". Original shows `text_excerpt` only on click, with a warning line. Esc and the scrim close it.
5. **Skipped line** under the progress bar from `stats.skipped_*` (S1). Hidden when all are 0.
6. **New folder.** Debounced `suggestEmoji` (500 ms), user can edit the emoji. `POST /folders`, then polls the job and refreshes counts.
7. **Browser AI** (commits 5f2c9c4, 27ddc16, 6d8e724, 8b907e1). `frontend/src/ai/browserAI.js`: `startBrowserAI`, `suggestEmoji`, `analyzeFile`, `runPrivacyPass`. Every function resolves and never rejects. Each model call times out after 20 s with null. The pass runs one file at a time, skips files whose `client_meta.sha256` equals the card `sha256`, and counts a 409 as skipped. `npm run fetch-models` downloads the pinned model files. `frontend/spikes/browser-ai-check.html` is the test page.
8. **States.** First-run empty (3 steps), skeleton loading, backend down (start command and Try again), scan errors, empty folder, no matches.
9. **Light and dark.** `prefers-color-scheme` plus a toggle saved in `localStorage`. System fonts only.

## Deviations from the spec, and why

| Deviation | Why |
|---|---|
| Desert Ant models run on the **main thread**, one at a time, no Web Worker | Owner decision in the Phase 0 and Phase 1 feedback: no worker shim. The spec said "ideally" a worker. |
| Browser models are **self-hosted** from `/models/<m>/` (gitignored, fetched by `npm run fetch-models`), with the Hugging Face default as fallback when the local file is missing | Owner decision. Keeps the browser from calling Hugging Face at run time. The fallback path was **not exercised** this round. |
| Gist `topics` hold topic **names** (for example "Travel"), not ids | That is what the Gist browser build returns. |
| A plain rescan does **not relink** unchanged files. Relinking happens when a file is re-indexed | Side effect of L4: only the new folder's links are written. A full relink is not offered. |
| `/export/snapshot` still **drops `sha256`** from cards | Not changed in this round. Demo mode (Phase 3) does not need it. |
| `vite build` output (`dist`) is **292 MB** (models 114 MB, three wasm cores of 46 MB each, litert-wasm about 46 MB) | The self-hosted models are copied from `public/models` into `dist`. Not reduced. |
| `scripts/smoke_test.py` does not exist yet, so its spec line was changed in text only | It is a Phase 3 file. |
| Phase 2 first screenshots used `?ai=off`, no models, one stand-in `/search` response | Replaced by the retake in the section "Screenshots" below once it is done. |

## Commands run, with trimmed output

All output copied from the round reports (`phase2-r1-backend.md`, `phase2-r1-ui.md`, `phase2-r1-browser-ai.md`). Nothing re-typed from memory.

Backend tests (`<repo>\backend`):

```
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
................................................                         [100%]
48 passed in 3.37s
```

Frontend build (`<repo>\frontend`, `npm run build`):

```
dist/assets/dist-B2502ad3.js   48.63 kB | gzip: 14.04 kB
built in 1.06s
```

Real-model backend check (`python testdata\r1_real_check.py <temp>\vf-r1 backend`; uvicorn on 127.0.0.1:8010, DB and files in `<temp>`, float32 because 4.0 GB was free):

```
scan done {"new": 7, ... "skipped_too_large": 0, "skipped_cloud_only": 0, "skipped_hidden_or_link": 0} 19s errors: []
  invoice INV-3307.pdf | ok | ['Finance & Receipts'] | title:model,summary:fallback,keywords:model+freq
  coffee receipt.txt   | fallback | ['Finance & Receipts'] | needle empty | title:fallback,summary:fallback,keywords:freq
  voice memo.wav       | ok | ['Finance & Receipts'] | title:fallback,summary:whistle,keywords:freq,note:needle empty
  budget screenshot.png| ok | ['Screenshots & Media'] ...
search 'money I spent'   100 coffee receipt.txt (Finance) | 62 invoice INV-3307.pdf (Finance) | 55 budget screenshot.png (Screenshots & Media)
search 'invoice'         90 invoice INV-3307.pdf | 65 voice memo.wav | 41 coffee receipt.txt
search 'Sam migration'   100 meeting notes.md | 54 journal.txt | 39 coffee receipt.txt
search 'zebra spaceship' results [] ; weak: 10 voice memo.wav, 9 invoice, 9 meeting notes
folder "Audio Memos" created; links before 7, after 8; lost (non-Unsorted): []; gained: voice memo.wav -> Audio Memos
read-only diff of the test folder: 0 hash diffs, 0 size/mtime diffs (7 files before and after)
```

Browser AI check page (headless Edge, `vite preview` on 4173, self-hosted models):

| Step | Result | Time |
|---|---|---|
| `?ai=off`, all five steps | all null/false, 0 external requests | 0 ms |
| `startBrowserAI` | redact, gist, emo loaded | 3894 ms |
| cached call | same | 0 ms |
| `suggestEmoji("Travel plans", ...)` | an emoji | 21 ms |
| `analyzeFile` (fake invoice) | has_pii true; GIVEN_NAME, SURNAME, BUILDING_NUMBER, STREET_NAME, CITY, EMAIL, PHONE; topics ["Travel"] | 92 ms |
| `analyzeFile` (empty text) | null | 0 ms |

Outbound requests during the browser run: only `POST` and `OPTIONS` to `events.desertant.com/api/v1/license` and `/api/v1/activate` (the disclosed license check). No huggingface.co, no jsDelivr.

Model files in `frontend/public/models/` (gitignored): 119,862,467 B (114 MB), tags redact v0.4.2, gist v2.2.0, emo v0.7.0.

## Known issues

- **"money I spent" fails the new Phase 3 rule.** Receipt 100, invoice 62, `budget screenshot.png` 55 (Screenshots & Media). The rule is "top 3 all Finance & Receipts". This test set has only 3 Finance files, and the third, `voice memo.wav` (speech says "pay the electricity invoice"), scored under the cut-off of 35 for this query. Cut-off 35 and the 0.7/0.3 blend are as the owner specified. **Not tuned toward this data.**
- "invoice" passes: the invoice is #1 (90).
- `runPrivacyPass` PATCH path was **untested** in the browser AI round because C1 had not landed. It is covered in the wiring section when that is done.
- Hugging Face fallback for browser models: not exercised.
- Each of the three wasm cores (about 46 MB) compiles on the main thread. Startup took 3.9 s with local model files.
- `vite preview` returns `index.html` for missing paths. The HEAD check in `browserAI.js` rejects `text/html` for that reason.
- Mirage per-call errors are not cached (only load errors).
- Cloud-only skip is tested with fake attributes only, not on a real OneDrive placeholder. Reparse and junction behaviour is unchanged and untested.
- UI: folder chip shows no % when the score is 0. Match values at or under 1 are read as fractions. Reclassify jobs are detected by the text "reclass", unverified against the real job name. The full file list is fetched once and filtered in the browser. Narrow-screen layout is only a basic 900 px breakpoint. The copy button and long-path wrapping were not checked.
