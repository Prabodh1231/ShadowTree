# Backend NICE fixes (code check + live check finding 6)

Sources: `reports/shadowtree/check-backend-code.md` (NICE 1-6, 8, 10-12) and `reports/shadowtree/live-check.md` (NICE 6).

## Commits on main (local, not pushed)
- `ff3ea9a` fix(backend): code-check NICE 1-6, 8, 10-12 (built on branch `fix/backend-nice` in a worktree, fast-forward merged)
- `6cf724a` fix(ocr): when OCR read the image, keep only Mirage's visual description
- `ea03111` style(ocr): imports before `NotDownloaded` in `ai_ocr.py`

## Fixes
| # | Fix | File:line |
|---|---|---|
| 1 | `"Global.use_cls": False` in the RapidOCR params: no angle classifier, so nothing can be fetched for it | `backend/app/ai_ocr.py:40` |
| 2 | `ppocrv5_dict.txt` is required in the `_load` check and in the `/health` `ocr` presence list; `Rec.rec_keys_path` is always passed | `backend/app/ai_ocr.py:31`, `backend/app/ai_classify.py:179` |
| 3 | No `ext_ver` stamp when OCR could not run (`error` or `skipped`), so the file is read again once models exist; scanner uses `card.get("ext_ver", ...)` | `backend/app/ai_cactus.py:366`, `backend/app/scanner.py:220` |
| 4 | `search.py` header rewritten to match `match_percent` (wording below) | `backend/app/search.py:9-16` |
| 5 | New `ai_ocr.NotDownloaded(NotReady)`; models not downloaded gives `ocr:skipped` and no note; real failures stay `ocr:error` with a note | `backend/app/ai_ocr.py:14`, `backend/app/ai_cactus.py:199-206,255,265` |
| 6 | `client_meta` is reset only when the sha256 changed (a one-time re-read of an unchanged file keeps the privacy scan) | `backend/app/scanner.py:222` |
| 8 | Stored vectors whose byte length is not `DIM * 4` are skipped in `cosine_top` and in the FTS-hit cosine lookup | `backend/app/search.py:81-83,148` |
| 10 | api_notes lines 3, 28, 35 reworded for the ONNX stack (no live "import gliclass" / GLiClass cache) | `docs/api_notes.md:3-5,28,35` |
| 11 | Dropped `rec_en` and `ppocrv5_en_dict.txt` from the downloader | `scripts/download_models.py:26-35` |
| 12 | Each PDF page closes in its own `try/finally` | `backend/app/extractors.py:89-99` |
| live 6 | When OCR returned lines, Mirage is called with `with_text=False`: only scene, style, regions and reasoning stay; its own text copy is dropped. OCR empty or failed: Mirage text kept as before | `backend/app/ai_cactus.py:151,166,269` |

Test stub change: the conftest `embed` stub now returns 256-d vectors (was 4096-d), because fix 8 skips any other length.

## New search.py header wording (for the README)
```
  3. match (0..100), see `match_percent`. Weights of the parts that exist are renormalised
     (each mix is divided by the sum of the weights it uses):
        confident (best z >= Z_USEFUL = -6, i.e. the reranker found a real match):
            mix = 0.6 * sigmoid((z + 4) / 2) + 0.3 * min(cos / 0.6, 1) + 0.1 * bm25_norm
        otherwise (reranker sees only noise, z about -11 for every file):
            semantic-only mix = min(cos / 0.35, 1); with FTS hits, bm25_norm joins at weight 0.3
            against 0.7 for the cosine part
        match = round(100 * mix) + name boost (+20 when every query word is in the name/title)
```

## Tests
New in `backend/tests/test_nice_fixes.py`: `test_3_ocr_error_leaves_no_stamp_and_is_reread`, `test_5_missing_ocr_models_is_skipped_not_a_fallback`, `test_6_reread_of_unchanged_file_keeps_client_meta`, `test_8_wrong_length_vector_is_skipped`, `test_live6_ocr_ok_drops_mirage_text_lines` (real `describe_image` with a fake Mirage; OCR ok drops "Ox80070005" and "ot save", OCR empty keeps them).

## Commands (trimmed)
```
git -C "C:\Users\prabo\Winter AI" worktree add "%TEMP%\st-backend-fix" -b fix/backend-nice HEAD
(worktree) python -m pytest -q -p no:cacheprovider        97 passed in 6.74s
(worktree) real OCR once on the sample screenshot with use_cls=False:
  ['Error', 'Payment failed', 'Could not save your invoice.', 'Error code 0x80070005: access denied.', 'Retry']   cfg.Global.use_cls = False
git merge --ff-only fix/backend-nice                        8eb6b76..ff3ea9a fast-forward, 10 files
(main) pytest -q                                            97 passed in 6.91s
git worktree remove %TEMP%\st-backend-fix ; git branch -d fix/backend-nice    Deleted branch fix/backend-nice (was ff3ea9a)
(main, after live 6 fix) pytest -q                          98 passed in 6.87s
real build_card on the sample screenshot (in-process, no port, no DB):
  ai_error: ocr:ok,title:fallback,summary:ocr,keywords:freq,note:needle empty
  Text in the image:
  Error / Payment failed / Could not save your invoice. / Error code 0x80070005: access denied. / Retry
  Image description:
  digital interface image. red rectangular button with white text, blue button, red border
```
The other chats' uncommitted files (`README.md`, `docs/demo_script.md`, `docs/devpost_story.md`, `docs/spec.md`, `.claude/`) were not touched.

Note: in this real run Needle returned nothing for the screenshot (`needle empty`), so the summary came from the OCR lines; in Step 4 Needle gave the summary. Needle output varies between runs; not caused by this change.

## Skipped (as instructed)
- 7: real-load-path tests for potion, RapidOCR and the FlashRank success path.
- 9: progress total for `relink_stale` / `embed_missing`.
- 13: FlashRank thread count.
- 14: batched NLI pairs.

Existing DBs: screenshots indexed before this fix keep Mirage's text copy until they are re-indexed (no version bump was added).
