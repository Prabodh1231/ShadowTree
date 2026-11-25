# ShadowTree: reviewer feedback

**Verdict: approved, with two time-boxed fixes.** About **6 hours remain** before the 03:30 IST deadline. Spend **at most 1.5 hours** on the fixes below, commit, and stop. Anything not finished by then gets listed under Known issues instead.

## What I checked myself

- `pytest -q`: **98 passed**. `pip check` is clean. No `torch`, `transformers` or `gliclass` in `requirements.txt` or `backend/app`.
- **Sample folder, live backend:** all 8 files land in the same folders with the same scores as the review note. Search results match the note.
- **Desktop app (`shadowtree.exe`):** it started the backend (`/health` → `app: ShadowTree`). Closing the window stopped the backend: port 8000 was released and the backend process was gone. ✅
- **Real folder** (this PC's OneDrive Documents, 138 files, scratch DB, aggregate counts only): scan done in 375 s, 0 errors, 4 files over 25 MB skipped. **112 of 142 files went to Unsorted (79%).** This confirms the "sorter is strict" known issue. A judge pointing the app at their own folder would see mostly Unsorted.

## Fix 1 (MUST, about 30 min): a best-guess folder instead of Unsorted

On the 135 text files from that real folder, the best topic-folder score is mostly 0.1–0.3:

| Rule | Sorted | Unsorted |
|---|---|---|
| now: only ≥ 0.5 | 23 | 112 |
| best folder if ≥ 0.2 | 58 | 77 |
| best folder if ≥ 0.1 | 92 | 43 |

Change the indexing rule:
- A file joins every topic folder with score ≥ 0.5, **as today**.
- **If none reaches 0.5, it joins its single best topic folder when that score is ≥ `SOFT_FLOOR` (default 0.15, configurable).** Store the real score.
- Below the floor, the file goes to Unsorted.
- Screenshots & Media still goes by file type.
- **New-folder jobs keep the strict ≥ 0.5 rule.** Otherwise every new folder would fill with weak matches.
- **UI:** a folder chip with a score under 0.5 gets a muted or dashed style and the tooltip "Best guess", so users can tell it apart from a confident match.

Acceptance:
- The sample folder is unchanged (same 9 links, Unsorted 0).
- A mocked test covers the soft-floor link and the below-floor Unsorted case.
- Re-run on a real folder and record the new Unsorted count in the review note.

## Fix 2 (SHOULD, time-box 1 hour): confident false hits in search

On the sample folder:
- **"tax documents"** → `research outline.md` **83%**, meeting notes 43%, bank note 39%. There are no tax files, so this should be "No strong matches".
- **"invoice"** → `Screenshot 2026-11-20.png` **70%** next to the invoice's 100%.
- "money I spent" → receipt 30% and invoice 27% are ranked 4th and 5th (already known).

Find why weak FlashRank logits still produce high matches. The `0.3 · min(cos/0.6, 1)` and fallback branches look like the likely cause. Tighten the formula so a high match needs real reranker agreement.

Acceptance on the samples:
- "tax documents" and "volcano penguin" → `results: []`, weak list only
- "invoice" → only the invoice above the cut-off
- "money I spent" → the receipt or invoice in the top 3
- "pay the bill", "my diary", "coffee" and "error message" still give the same top hit as now

Put these 8 queries in a small real-model check script and paste its output into the review note. **If the hour runs out, stop**, keep the current formula, and list the cases under Known issues.

## Small things (only if quick)
- `backend/app/ai_classify.py` module docstring still says "`classify` raises `NotReady` until DeBERTa (Step 3) is wired". Update it.
- README: add a scan-speed note, about 2–3 s per file on a real folder (OCR and Mirage on PDFs and images).

## After the fixes
Commit, update `docs/review/shadowtree.md` (Fix 1 numbers, Fix 2 query output), and **stop**. The reviewer then re-records the demo video in the ShadowTree window. **Do not start anything else**: no Silero, Moonshine, Eye or installer work.
