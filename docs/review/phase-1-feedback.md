# Phase 1: reviewer feedback

**Verdict: approved once the four MUST-FIX items below are done.** Fix them, then go straight on to Phase 2. No second review stop is needed. List the fixes at the top of `docs/review/phase-2.md`.

The work is solid. The read-only design holds, the review notes are honest, and the Origin and TrustedHost checks are a good addition.

## What I checked myself

- `pytest -q`: **29 passed** (2.5 s).
- Read `scanner.py`, `search.py` and the first half of `main.py`. The only `open()` calls are `"rb"`, and the only `mkdir`s are the data dir and DB parent.
- **Real-world walk on this PC's OneDrive folders.** Here Documents and Desktop sit inside OneDrive and carry the `ReparsePoint` attribute. I was worried N9 would skip them entirely, but `scanner.walk()` found 134 of 138 supported files in Documents and all 20 on Desktop. The 4 it missed are PDFs over 25 MB, which is the intended limit. **N9 is not a demo-breaker.** But the user is never told that files were skipped (see S1).

## MUST-FIX

1. **L4: creating a folder must not remove existing links.** This is a key demo moment ("make a folder, watch files flow in"). If the invoices drop out of Finance at that point, the app looks broken. On `POST /folders`, score every file against the **full** label set (that keeps calibration the same), but **write only the new folder's links**. If a file gains a link to the new folder, also remove its Unsorted link. Leave every other link alone. A full relink happens only on an explicit rescan. Add a test: create a folder, and every existing link is still there.
2. **L1: search relevance.**
   - Add a **minimum cut-off**: drop results with `match < 35`. Return `{"results": [], "weak": [...top 3 below cut-off]}` so the UI can say "No strong matches. Closest:".
   - Add a **name/title boost**: if every non-stopword query token appears in the file's name or title (case-insensitive, prefix ok), add +20 before clamping. Then the query "invoice" finds `invoice INV-3307.pdf` first.
   - **Cap candidates** (also fixes N6): at most 40 FTS hits + 20 recent files. Rerank in batches of 16, and release the model lock between batches so a running scan isn't blocked for long.
   - **Change the acceptance test.** For "money I spent", a receipt ranking first is a correct answer. The new rule: **the top 3 results all belong to Finance & Receipts**, and for "invoice" the invoice file is #1. Update `docs/spec.md` (Phase 3 smoke test) to match.
3. **L2: guard against Needle hallucinations.** Accept a model `summary` or `title` only if at least 90% of its word tokens (lowercased, length > 2) appear in the source text. Otherwise use the fallback, with provenance `summary:fallback(ungrounded)`. Add a unit test with the "digitale migration" case.
4. **N3: a folder that can't be listed must not shrink the index.** Track the folders that failed to list or stat during the walk, and skip the "removed" step for any DB path inside them. Test with a monkeypatched `os.scandir` that raises for one subfolder.

## SHOULD-FIX (small, do them in the same pass)

- **S1: report the files that were skipped.** Add `skipped_too_large`, `skipped_cloud_only` and `skipped_hidden_or_link` counts to the scan `stats`. For cloud-only, skip a file only if it has `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (0x400000) or `OFFLINE` (0x1000), because reading it would trigger a download. Hydrated OneDrive files must keep being indexed, since they work today. Phase 2 shows these counts as a line under the progress bar, e.g. "4 files over 25 MB skipped".
- **N2:** write `scan_root` only after `jobs.start_scan()` succeeds.
- **L3:** keep `ai_error` to one line of at most 200 characters (first line of the exception, then `…`). Keep the provenance suffix.
- **L5:** make `ai_status` and `ai_error` consistent. If the status is `ok`, `ai_error` holds only the provenance (e.g. `title:model,summary:fallback`), never "needle returned nothing". Put that note in the provenance instead.
- **L6:** use the same shape for `/health` `files_present` on both stacks: `{"<model>": bool}`. Also check the Cactus engine DLL (N10) and remove the dead clause.
- **N5:** cache any Whistle or Mirage load error for the rest of the job, not just `ImportError`.
- **N7:** assert the full `["explorer", "/select,", path]` argument list in the test.
- **N11:** fix the stray `?` in `_ONLY_NUM_DATE`.
- **C-2:** add `…` when a summary is cut.
- **L8:** the README should say to run uvicorn in the foreground and stop it with **Ctrl+C**. Don't use `Start-Process` in user-facing docs.
- **`docs/spec.md`:** update the "no telemetry" line to match the steering rule, so the two documents don't contradict each other.

## Won't fix (fine as is)

N8 (bounded by the thread pool), L7 (internal asyncio socketpair), C-3, C-7, and N12's remaining test gaps, apart from the tests added by the MUST-FIX items above.

## For Phase 2 (carry forward, nothing new)

Desert Ant credit in the sidebar footer, self-hosted browser models with HF fallback, Desert Ant on the main thread (no worker shim), the skipped-files line (S1), the "No strong matches. Closest:" state (MUST-FIX 2), and a subtle `ai_status` indicator on each card.
