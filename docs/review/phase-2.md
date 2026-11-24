# Phase 2 review note: Frontend and browser AI

Nothing is pushed. Everything is on local `main`.

## Phase 1 review fixes (owner list, `docs/review/phase-1-feedback.md`)

Backend tests are in `backend/tests/test_review_fixes.py` unless noted.

| ID | What changed | Commit | Test |
|---|---|---|---|
| (feedback) | Reviewer feedback file added | 5003c15 | none |
| C1 | `sha256` on `/files` cards. `PATCH /files/{id}/client-meta` requires `sha256`, checks it, returns 409 on mismatch, stores it in `client_meta` | 0c20307 | `test_c1_cards_have_sha256_and_patch_checks_it`, `test_api.py::test_sensitive_counts_and_client_meta` (updated) |
| L4 (MUST) | `POST /folders` scores against all labels, writes only the new folder's links, drops Unsorted only for files that gain a link. `scanner.link_new_folders` replaces `reclassify_all` | b0b2db5 | `test_l4_new_folder_keeps_existing_links` |
| L1 (MUST) | Cut-off 35, `weak` list (top 3, `[]` when results exist), +20 name/title boost, 40 FTS + 20 recent candidates, batches of 16 with the model lock released between batches | bf729e6 | `test_l1_name_boost_rules`, `test_l1_cutoff_weak_and_shape`, `test_l1_invoice_name_boost_ranks_it_first`, `test_l1_candidates_capped_and_batched` |
| L2 (MUST) | Model title or summary kept only if at least 90% of its tokens (lowercase, length over 2) are in the source text. Else fallback, provenance `summary:fallback(ungrounded)` or `title:fallback(ungrounded)` | 3a69899 | `test_l2_is_grounded_digitale_migration`, `test_l2_build_card_uses_fallback_for_ungrounded_summary` |
| N3 (MUST) | Folders that failed to list are tracked, and the "removed" step skips DB paths inside them (13fa41d). **Half done at first:** the review (`phase2-r1-backend-review.md`) found that a failed `stat()` or `is_dir()` was logged but not tracked, so those rows were still deleted. The edit had been written but did not apply. Fixed: such paths now go to `unreadable` too | 13fa41d, fix 87e3bf3 | `test_n3_unreadable_folder_keeps_its_rows` (monkeypatched `os.scandir`); `test_n3_stat_failure_keeps_rows` (`DirEntry.stat` raises for one file and one folder; both keep their rows, a deleted file is still removed) |
| S1 | `skipped_too_large`, `skipped_cloud_only`, `skipped_hidden_or_link` always in scan stats as ints. Cloud-only means attribute `0x400000` or `0x1000` only | 6887240 | `test_s1_skip_counts_with_fake_attributes`, `test_s1_keys_present_without_skips` |
| N2 | `scan_root` is written only after `start_scan` succeeds | 1cc6deb | `test_n2_refused_scan_does_not_change_scan_root` |
| L3 | `ai_error` is one line, at most 200 chars, cut text ends in an ellipsis, provenance suffix kept | 04a8d1a | `test_l3_ai_error_is_one_short_line` |
| L5 | Status `ok` keeps only provenance in `ai_error`. Side notes become `note:...` tokens | 04a8d1a | `test_l5_ok_status_has_only_provenance` |
| L6 / N10 | `/health` `files_present` is `{"<model>": bool}` on both stacks. Cactus models need the weights and `libcactus.dll`. Dead `or "whistle" in loaded` clause removed | 9718ff0 | `test_l6_files_present_shape_on_both_stacks`, `test_n10_cactus_needs_the_engine_dll` |
| N5 | Any Whistle load error is cached for the rest of a job (Mirage already cached any load error). The review noted the cache never reset, so one bad audio file disabled Whistle until restart. Fixed: `ai_cactus.reset_failures()` runs at the start of every job. GLiClass' own load-error cache is not reset | a926ab6, fix 87e3bf3 | `test_n5_whistle_load_error_is_cached`; `test_n5_failure_cache_is_cleared_at_job_start` |
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

Backend tests (`<repo>\backend`), first run after the round 1 fixes (the N3 and N5 fixes below bring it to 50 passed in 3.73s):

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

## Round 2: wiring check against the backend contract (commit 1972047)

Source: the round 2 wiring report. Backend read at 4e729d4. The check used a `git archive HEAD` copy in `<temp>`, a backend on 127.0.0.1:8011, `vite preview` on 4173 and headless Edge over CDP. It had **no backend models** (every file Unsorted, `ai_status` fallback). Browser models were self-hosted. The model lock was taken with 4148 MB free and deleted after.

Fix: `1972047 fix(ui): match the real reclassify job kind exactly` (`frontend/src/main.js`, one line: exact `"reclassify"` instead of a text match on "reclass"). Also landed in this window: `87e3bf3 fix(scanner): N3 also keep rows when stat or is_dir fails; N5 clear model failure cache at each job start`. No other mismatch was found between UI and backend (`sha256` on cards, PATCH 409, `{results, weak}`, `/scan/status` fields, `skipped_*` stats).

Commands (trimmed): `git archive --format=zip -o <temp>\veilfs-r2\be.zip HEAD backend`, then uvicorn on 127.0.0.1:8011 with the data dir in `<temp>`, `python testdata\make_test_folder.py <temp>\veilfs-r2\files` (7 files), `$env:VITE_API_BASE="http://127.0.0.1:8011"; npm run build; node node_modules\vite\bin\vite.js preview`. `npm run build` printed `built in 1.04s`.

| Check | Result | Numbers |
|---|---|---|
| Privacy pass PATCHes every file | PASS | 7 PATCH, all 200, 10 s from scan end to last PATCH. All 7 cards: `client_meta.sha256 == sha256` |
| Second pass skips all | PASS | reload: 0 PATCH, 0 `GET /files/{id}` |
| Stale sha256 gets 409, UI survives | PASS | 1 PATCH with status 409, 7 cards still shown, no error note, no toast, metadata stayed empty |
| Sensitive (PII) folder | PASS | 5 files (coffee receipt, invoice, journal, meeting notes, voice memo). Sidebar count 5 |
| Drawer shows redacted excerpt by default | PASS | `Customer: [GIVEN_NAME_1] [SURNAME_1], [EMAIL_1], phone [PHONE_1]` |
| New folder suggests an emoji | PASS | "Travel plans" gave a plane emoji after 2.5 s |
| Job kind after `POST /folders` | PASS | `kind: "reclassify"`, done, 8 of 8 |
| Skipped line from a real response | PASS | "1 file over 25 MB skipped · 1 hidden or linked file skipped" |
| "No strong matches. Closest:" | PASS with a caveat | Without GLiClass no real query scored under 35. Checked with `MIN_MATCH = 101` in the **temp copy only**: 0 results, 1 weak, UI showed the state. An unknown query gave the plain no-matches state |
| Hugging Face fallback | PASS | dist copy without `models\`: 7 GET + 7 PATCH, all 200, within 150 s. Hosts: 127.0.0.1, huggingface.co, us.aws.cdn.hf.co, events.desertant.com |
| Read-only | PASS | SHA-256 of all 7 test files identical before and after |

The `runPrivacyPass` PATCH path and the Hugging Face fallback, listed as untested earlier, are tested by this round.

Known issues added by this round:
- `voice memo.wav` is flagged PII. The redactor tags "16000 Hz" in the metadata line as ZIP_CODE and a city. Images and audio with no OCR or transcript text only have a metadata line, so false PII is likely for them. Not fixed.
- A reclassify job with no backend models puts long GLiClass messages in `errors`. The UI shows the first 3 as red notes. Seen only without models.
- Gist topics are broad ("Technology & Software" appears on most files).
- Real weak matches from GLiClass were not seen in that round.

## Screenshots (retaken with real models)

`docs/review/phase-2-shots/`: 01 first run, 02 grid, 03 drawer, 04 search, 05 weak matches, 06 backend down. Each in light and dark, 1920x1080. 01 to 05 were retaken with the **real backend models** (GLiClass float32, Needle, Whistle, Mirage; 5.6 GB was free) and the **browser AI on** (no `?ai=off`). Shot 05 is a real response: query "zebra spaceship" returned `results: []` and three `weak` cards (10%, 9%, 9%). No stand-in response is used any more. Shot 06 (backend down) is unchanged from the first round and needs no models.

Setup: `git archive HEAD` copy of `backend` in `<temp>`, model cache copied into a data dir in `<temp>`, uvicorn on 127.0.0.1:8000, `vite` dev on 127.0.0.1:5173, test files from `make_test_folder.py` into `C:\VeilFS Demo\messy folder` (no user name in the path; deleted after). The driver waits until all 7 files have `client_meta.sha256` before taking shots. `shoot.mjs` in that folder is the driver as last run (shots 02 to 05 only; for 01 the first-run loop was removed because the DB was no longer empty, those two came from an earlier run of the same driver on an empty DB). Model lock taken and deleted. Server, vite and Edge stopped.

What the shots show: titles and folders from the models (Finance & Receipts 3, Work & Research 2, Personal & Notes 1, Screenshots & Media 1, Unsorted 0), PII badges on 4 files, and in the drawer a redacted excerpt (`Customer: [GIVEN_NAME_1] [SURNAME_1], [EMAIL_1], phone [PHONE_1]`). Shot 04 "money I spent" shows receipt 100%, invoice 62%, budget screenshot 55% (the known issue below).

Visible flaws in the shots, not fixed:
- The drawer **Summary** line shows the original text, including the fake name, email and phone. Only the excerpt box is redacted.
- The redactor leaves `Card ending 4242` in the excerpt.
- Sensitive (PII) counts 4 here. In the wiring round it was 5 (`voice memo.wav` was flagged there), so PII flagging of the audio file varies between runs.
- Several files show the broad Gist topic "Technology & Software", and `budget screenshot.png` also has "Business & Entrepreneurship".
- Paths in cards are cut on the left (`…mo\messy folder\...`).

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
