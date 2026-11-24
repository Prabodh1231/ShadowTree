# Final phase note

Base: `02d0fb6` (end of Phase 2). All commits are on local `main`. Nothing is pushed.

## Done (`git log 02d0fb6..HEAD`)

| Sha | What |
|---|---|
| `62ba3ab` | Keywords from the model must be grounded: at least 90% of their words appear in the file, at most 4 words and 30 characters. Frequency keywords top up to 6. |
| `117c1f2` | UI hides PII in keyword tags and titles of PII files (cards, search results, drawer). |
| `596fe78` | `scripts\make_samples.py`: 8 fake sample files. `fpdf2` and `fonttools` pinned in `backend\requirements.txt`. `sample_messy_folder/` is gitignored. |
| `9e4b2fe` | Owner feedback files for Phase 2 and the fast track. |
| `2201044` | UI hides title and keywords of a file until the privacy pass has checked it. |
| `5102b8e` | Cards show while a scan runs (refetch every 2 s). Topics capped at 2 with score 0.5 or more. |
| `a2529a2` | MIT `LICENSE`. |
| `86fa556` | First README commit. Incomplete: it held only the privacy section. Replaced by the next one. |
| `124ae75` | Full README: pitch, problem, audience, Mermaid diagram, PowerShell commands, sizes, RAM, limits, credits and licenses. |
| `055fe42` | `docs\demo_script.md`, a 2.5 minute script. |

## Skipped

- `smoke_test.py`, the GitHub Pages demo build, and `/export/snapshot` (fast track says skip).
- The rest of the Phase 2 SHOULD-FIX list.
- **README screenshots (`docs\screenshots\`).** Skipped for time and low free memory. The README has no screenshot section. The 12 PNGs in `docs\review\phase-2-shots\` are older review shots with fake PII, kept as review evidence only.
- README commands were matched to real scripts and files by reading them. They were not run in a fresh clone.

## Commands run (output copied from the worker notes, trimmed)

Keywords (`62ba3ab`, from `final-b-keywords.md`):

```
.....................................................                    [100%]
53 passed in 4.38s
```

Samples (`596fe78`, from `final-c-samples.md`):

```
backend\.venv\Scripts\python.exe -m pip install fpdf2     -> fpdf2 2.9.0, fonttools 4.68.0
backend\.venv\Scripts\python.exe scripts\make_samples.py "%TEMP%\vf-samples\Bob's test dir"
  bank transfer note.txt 247, coffee receipt.txt 222, invoice-2041.pdf 1345, journal.txt 204,
  meeting notes.md 186, research outline.md 264, Screenshot 2026-11-20.png 14720, voice memo.wav 113966 (16 kHz mono)
scan done {"new": 8, ...} 20s errors: []
```

Hand check on the samples (real models, DB in %TEMP%):

| Check | Result |
|---|---|
| 8 files indexed, no errors | PASS (20 s) |
| File hashes and mtimes unchanged | PASS (0 diffs) |
| "invoice": invoice-2041.pdf first | PASS |
| "money I spent": receipt or invoice first | PASS: coffee receipt first, invoice second |
| Spaces and apostrophe in path | PASS |

No output exists for the frontend steps (`2201044`, `5102b8e`); `final-a-frontend.md` was empty when this note was written. They were not re-run by this chat.

## Known issues

- Needle returned empty text for 3 sample files (`coffee receipt.txt`, `journal.txt`, `research outline.md`), so the fallback title and summary were used.
- `voice memo.wav` lands in "Screenshots & Media" until the user makes an audio folder.
- `bank transfer note.txt` did not show up for "money I spent". Search relevance is approximate.
- The backend still returns raw keywords and titles of PII files. The UI hides them (loopback only).
- Needle is extractive. Windows only. The Desert Ant license check cannot be turned off.
- The README has no screenshots yet.
