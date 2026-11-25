# ShadowTree demo script (about 2.5 minutes)

Before recording: the desktop app is running (`cd frontend; npm run tauri dev`, it starts the backend itself), the sample folder exists (`scripts\make_samples.py`), and the models have loaded once. Use a folder path that has no user name in it.

| # | Time | Click | Say |
|---|---|---|---|
| 1 | 0:00 | Open File Explorer on `sample_messy_folder`. Show the 8 files with messy names. | "This is a normal messy folder. `scan`, `Screenshot`, `voice memo`. I can't tell what is inside without opening each one." |
| 2 | 0:20 | Click the ShadowTree window. Point at the "Powered by Desert Ant Labs" footer only if asked. | "ShadowTree is a virtual file system. It sorts files with AI that runs on this PC. It never moves or changes my real files." |
| 3 | 0:30 | Drag the `sample_messy_folder` folder onto the window (or press **Choose folder**). Press **Index (Read-Only)**. | "I drop the folder on the window and press Index. It only reads." |
| 4 | 0:45 | Watch cards appear ("Reading your files…"). Click **All Files**, then a folder in the sidebar. | "Files show up while it reads. Each has a title, a summary and tags. The PDF, the screenshot (text read from the picture) and even the voice memo are understood." |
| 5 | 1:10 | Click **Sensitive (PII)**. Open the invoice card. In the drawer, toggle **Redacted**. | "Files with personal data land here. Emails and phone numbers are found on my machine and hidden in the Redacted view." |
| 6 | 1:35 | In **New Virtual Folder**, type the name `Bills to pay` and the description `invoices, bills and payments that are due`. Note the emoji suggested. Press create. | "I can make my own folder. The app picks an emoji. It picks up the invoice and the voice memo where I said to pay the bill, by meaning, not by file name." |
| 7 | 1:55 | Click the search box. Type `invoice`, then `pay the bill`, then `my diary`. | "I search in plain words. `invoice` finds the invoice first. `pay the bill` finds the voice memo where I said it. `my diary` finds my journal. It ranks by meaning, not only by file name." |
| 8 | 2:10 | Open a result. Press **Reveal on Disk**. File Explorer opens on the real file. | "Reveal on Disk jumps to the real file." |
| 9 | 2:20 | Show the Explorer folder again. Same 8 files, same names, no new files. | "My folder is exactly as it was. No files moved, none added. Everything ran on this PC." |
| 10 | 2:30 | End on the grid. | "ShadowTree. Tidy view, same files, nothing leaves your computer." |

Tips: while a card is still being privacy-checked (about 15 s for the 8 samples) it shows only its file name and "Checking privacy...". Wait for the summaries before you talk about them. if the first search is slow, run it once before recording. Closing the window stops the backend. Search queries that land well on the sample folder: `invoice`, `pay the bill`, `my diary`, `meeting`. Avoid `money I spent`: the bank transfer note comes first. On the sample folder the receipt, invoice and bank note go to Finance & Receipts, meeting notes and the research outline to Work & Research, the journal to Personal & Notes, and the screenshot and voice memo to Screenshots & Media.
