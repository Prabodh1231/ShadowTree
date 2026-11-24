# Phase 1: verification summary

Three independent checks were run on the Phase 1 backend. This note trims them to the findings. The builder's own commands and
output are in `docs/review/phase-1.md` ("Commands and output").

## Who checked what, and how

| Check | Range or commit | Method | Result |
|---|---|---|---|
| Early review | `1c2580a..f64a274` (base `c26706b`) | Read-only: `git archive` copy in `%TEMP%`, diff read, mocked tests run from the copy, extra probes with `TestClient` and a temp DB. No server, no real model. | 0 MUST-FIX, 12 NICE (N1-N12). In that range there were no tests yet; the next commit (`045b4ef`) gave 29 passed. |
| Code check | `90d2c47..e011491` | Read-only: `git archive e011491` copy in `%TEMP%`, diff read, mocked `pytest -q` from the copy. No downloader, server or real model. | 1 MUST-FIX (M-A), 7 new NICE, status of N1-N12. `29 passed in 2.85 s`. |
| Live check | `e011491` | Real models, real server (`--host 127.0.0.1 --workers 1`, no reload), temp folder with a space and an apostrophe, its own DB through `VEILFS_DB_PATH`, float32. | 0 MUST-FIX, 11 of 12 checks pass, check 6 fails, 8 NICE. |
| Builder fix | `630dd48..315e7f2` | Docs only. | M-A fixed (below). |

## MUST-FIX

| ID | Finding | Status |
|---|---|---|
| M-A | `docs/review/phase-1.md` lacked "the exact commands you ran with their (trimmed) output" (`docs/spec.md:15`). | **Fixed in `630dd48`** ("Commands and output" section). Related docs commits: `5ed7bd4` (deviations 10-14), `e61d806` (known issues N2-N12), `315e7f2` (README commands). |

No other MUST-FIX in any of the three checks.

## Live check, 12 checks

| # | Check | Result |
|---|---|---|
| 1 | pytest (`-p no:cacheprovider`) | PASS, 29 passed in 2.35 s |
| 2 | Loopback bind and CORS (bad Origin 403, bad Host 400) | PASS |
| 3 | `/health` with models present and missing | PASS |
| 4 | `POST /scan` (7 indexed; big, `node_modules` and hidden files skipped; 44.1 kHz WAV transcribed) | PASS |
| 5 | Invoice in Finance, `POST /folders` starts reclassify (201, 409 on duplicate, 422 on bad body) | PASS |
| 6 | Search "money I spent": invoice first | **FAIL**, invoice is third |
| 7 | `/reveal` (200 for a path with space and apostrophe; 404, 422 on bad input) | PASS |
| 8 | client-meta validation and `/export/snapshot` (relative paths, no sha256, no excerpt) | PASS |
| 9 | Rescan, edit, delete (`skipped=7`; then `changed=1 skipped=5 removed=1`) | PASS |
| 10 | Read-only diff (hash, size, mtime ticks, listing; no new file; no DB in the repo) | PASS |
| 11 | No remote connections (only loopback addresses seen on the server PID) | PASS |
| 12 | Peak memory (float32): 2.43 GB at end of scan, 2.57 GB after searches | Recorded, as expected (about 2.3 GB) |

### Check 6: search relevance (known relevance issue, not a MUST-FIX)

```
q=money I spent  rerank=true
receipt.txt          score=0.484 match=100
screenshot budget    score=0.357 match=74
invoice INV-3307.pdf score=0.331 match=68
```

The invoice is third. Nothing crashes and no rule is broken, so the checkers rated it a relevance problem. The builder's own run saw the
same kind of ranking (rental PDF above the invoice). It is recorded in `docs/review/phase-1.md` "Known issues" and left to the owner.
Related: "invoice" ranks a voice memo (73) above the invoice PDF (70), and unrelated files still show 25-42 because there is no
minimum cut-off.

## Open NICE items

Each line: item, location. All stay open; the owner decides. (Numbering: N = early review, L = live check.)

- N2 `/scan` 409 still overwrites `scan_root`: `backend/app/main.py:114-117`.
- N3 unlistable folder deletes its rows: `backend/app/scanner.py:35-38,157-161`.
- N5 only `ImportError` from Whistle is cached: `backend/app/ai_cactus.py:159-161`.
- N6 `/search` holds the model lock for a long rerank: `backend/app/search.py:66-69`, `backend/app/ai_classify.py:80-91`.
- N7 `/reveal` test checks only `args[0][0]`: `backend/tests/test_api.py:60`.
- N8 per-request thread connections never closed: `backend/app/db.py:78-87`.
- N9 reparse-point skip hides OneDrive placeholders: `backend/app/scanner.py:19,24`.
- N10 dead `/health` clause; engine DLL not checked: `backend/app/ai_cactus.py:81`, `backend/app/ai_classify.py:120-122`.
- N11 stray `?` in `_ONLY_NUM_DATE`: `backend/app/extractors.py:107`.
- N12 test gaps (PDF text, 25 MB edge, summary, keyword cap, 25+ labels): `backend/tests/test_extractors.py`.
- C-2 `ai_cactus.py:236` summary has no ellipsis when OCR text is cut at 300 characters.
- C-3 `search.py:7` comment omits the 0.15 floor on "best hit shows 100".
- C-7 `spikes/needle_single_field.py` imports `app.config` and `app.ai_cactus` (allowed direction; no fix needed unless spikes must be standalone).
- L1 weak relevance, no minimum cut-off, invoice not first: `backend/app/search.py` (match formula, rerank).
- L2 Needle junk accepted as `summary:model` ("Sam owns the API migration digitale migration"): `backend/app/ai_cactus.py` (summary merge).
- L3 `ai_error` is long and multi-line with models missing (about 700 characters per file): `backend/app/ai_cactus.py`, `backend/app/scanner.py`.
- L4 adding a folder can drop existing links, because scores are relative to the label set: `backend/app/scanner.py` (`reclassify_all`).
- L5 `ai_status=ok` next to `ai_error="needle returned nothing"`, provenance suffix not always visible: `backend/app/ai_cactus.py` (`build_card`).
- L6 `/health` `files_present` is a dict for Cactus and a bool for GLiClass: `backend/app/main.py:79`.
- L7 asyncio opens a socket bound to `0.0.0.0` on Windows (internal socketpair, connects only to 127.0.0.1): no code location.
- L8 the venv `python.exe` is a launcher, so the PID from `Start-Process` is not the server PID; stopping only the launcher may leave the server running: README stop instructions.

Closed since the early review: N1 (run command and `phase-1.md` exist), N4 (documented on purpose in `phase-1.md`), README NICE 1 (`315e7f2`).

## Not checked by anyone

AI call counts on rescan (inferred from `skipped` and `indexed_at`), Windows junction skipping, hidden-dir skip beyond the Hidden
attribute, hung model calls, `scripts/download_models.py` on a clean machine, and Explorer selection by eye in the live check
(the builder read it back through `Shell.Application`).
