# Phase 2: reviewer feedback

**Verdict: approved once the two MUST-FIX items are done.** After that, go straight on to Phase 3 and list the fixes at the top of `docs/review/phase-3.md`.

All Phase 1 MUST-FIX items are done and tested. The UI looks good, and the drawer's Redacted/Original handling is careful.

## What I checked myself

- `pytest -q`: **50 passed**.
- Read `search.py` (cut-off 35, +20 boost, 40+20 candidates, batches of 16) and `scanner.link_new_folders`. The L4 behaviour is right.
- **Live run with real models**, on my own 6-file test folder (receipt, invoice, standup notes in a subfolder, trip ideas, a PNG screenshot, a WAV), with its own DB and real backend models, opened in a browser:
  - Scan: 6 new files, 0 errors, all `ok`, every file in a sensible folder. Receipt and invoice went to Finance (0.98/0.96), the voice note to Finance (0.80), standup to Work (0.99), the screenshot to Screenshots (0.93), and trip ideas to Personal (0.79).
  - Privacy pass: 3 files flagged PII. The drawer opens in Redacted view, with the summary and excerpt both redacted.
  - New folder "Travel & Outings": Emo suggested 🗺️. "trip ideas.md" gained the link (0.99) **and kept** Personal & Notes (0.79). Every other folder count stayed the same. ✅
  - Search "money I spent": receipt 100, invoice 54, nothing else above the cut-off. That's fine.
  - Network: only `127.0.0.1` plus 6 requests to `events.desertant.com` (the disclosed license check). No Hugging Face, no CDN.
  - Read-only: SHA-256 of all 6 files identical before and after, no new files.

## MUST-FIX

1. **Keyword tags leak the PII that the summary hides.** On PII-flagged files the summary is redacted, but the keyword chips still show names:
   - `invoice-1042.txt` → summary "Bill to: [GIVEN_NAME_1] [SURNAME_1]…", chips include **`jordan`**
   - `standup.md` → summary "[GIVEN_NAME_1] finished the login API…", chips include **`priya`**

   For files with `client_meta.has_pii`, run the same redaction over the **title and each keyword**. Hide any keyword that contains (case-insensitively) an `original` value from the Redact items, or one that Redact changes. Apply this everywhere a card renders (grid, search results, drawer). If the model isn't loaded, hide all keywords on PII files, the same rule as "Summary hidden: personal data". Add a check to the browser AI check page for this case.
2. **Ground the keywords too (extend L2).** Needle made up a keyword: the receipt shows the chip **"Bread $2.80 miljard"** ("miljard" isn't in the file). Apply the same 90% grounding rule to each model keyword and drop the ones that fail, then top up from frequency keywords as usual. Also drop keywords longer than 4 words, or longer than 30 characters. "Total paid: $10.10" is a copied line, not a keyword.

## SHOULD-FIX (do them in the same pass; they show up in the demo video)

- **Cards should appear while the scan runs.** Today the page keeps the empty state ("Choose a folder to index" button) until the whole scan ends. While a scan runs, refetch `/files` every 2 s and show new cards as they arrive, and replace the empty state with a "Reading your files…" state. Watching files sort themselves is the best moment in the video.
- **Fewer, better topics.** Gist adds broad topics to almost everything ("Technology & Software" on an invoice, "Business & Entrepreneurship" on standup notes). Show at most 2 topics with score ≥ 0.5, and none if no topic reaches that.
- **Redact false positives.** "receipt #8812" became `#[ZIP_CODE_1]`, and "16000 Hz" became a ZIP code too (Kiro's note). Don't send the generated metadata line (e.g. "WAV audio, 5.0 s, 16000 Hz") to Redact. Ignore `ZIP_CODE` items that come straight after `#` or are followed by `Hz`/`kHz`.
- **Red console noise.** LiteRT prints its INFO and WARNING lines as `console.error` (about 20 red lines on load). Try `DesertAnt.logLevel = 'error'` or a `Module.printErr` filter. If neither works, leave it and note it.
- **Retake the screenshots in Phase 3** after these fixes (the current ones show unredacted summaries).

## Phase 3 rule update

The "money I spent" rule depends on the data. Use this rule in `smoke_test.py` instead: **every result above the cut-off is in Finance & Receipts, and #1 is the receipt or the invoice.** Also make sure the generated sample set has **at least 3 clearly financial text files** (receipt, invoice, and e.g. a bank-transfer note), so the demo search shows a full row of hits.

## Not changed (fine as is)

Main-thread models (3.9 s startup), the 292 MB `dist` (the Phase 3 demo build drops Desert Ant anyway), and the `vite preview` HTML fallback handling.
