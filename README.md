# VeilFS

A local, non-destructive virtual file system for Windows. Full README in Phase 4.

PowerShell run commands (Phase 1 backend). The full list arrives in Phase 4; the commands with their output are in `docs/review/phase-1.md`.

```powershell
# from the repo root: download the models once
backend\.venv\Scripts\python.exe scripts\download_models.py
# from backend\: start the server in the foreground (no --reload). Stop it with Ctrl+C.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
# from frontend\, once: fetch the browser models (Desert Ant, about 114 MB) into frontend\public\models\
cd frontend; npm run fetch-models
```

## Network & privacy

File contents, text, summaries and results never leave your machine. These are the only outbound requests VeilFS makes:

| # | Request | When | Hosts | What |
|---|---|---|---|---|
| 1 | Backend model downloads | Once, by `scripts/download_models.py` (run it with `backend\.venv\Scripts\python.exe scripts\download_models.py`) | `huggingface.co`, `us.aws.cdn.hf.co` | Repos `Cactus-Compute/cactus` (engine `libcactus.dll`, 1.9 MB), `Cactus-Compute/needle3` (35.3 MB), `Cactus-Compute/whistle` (16.9 MB), `Cactus-Compute/mirage` (21.6 MB), `knowledgator/gliclass-v4-edge` (882 MB). After that the backend runs with `HF_HUB_OFFLINE=1` and Cactus telemetry off (`CACTUS_TELEMETRY=0`, `DO_NOT_TRACK=1`). |
| 2 | Browser model downloads | Once, by `npm run fetch-models`; and when the app loads a model whose local files are missing | `huggingface.co`, `us.aws.cdn.hf.co` | `desert-ant-labs/redact` v0.4.2, `desert-ant-labs/gist` v2.2.0, `desert-ant-labs/emo` v0.7.0. `cd frontend; npm run fetch-models` downloads them once (about 114 MB) into `frontend\public\models\`. The app then loads them from there, with Hugging Face as the fallback if those files are missing. |
| 3 | Desert Ant license check | Browser only, when the app loads a Desert Ant model (from Phase 2) | `events.desertant.com` | `POST https://events.desertant.com/api/v1/license` and `/api/v1/activate`. Sends a random install ID, the site domain, the model and its version, the SDK name and version, and the platform (and an API key if one is set; VeilFS sets none). It never sends inputs, outputs or file content. It has no opt-out, and VeilFS does not block, spoof or redirect it (license section 6). If it fails, the model still runs. |

Nothing else: no cloud AI APIs, no analytics.

**License version.** The npm packages `@desert-ant-labs/*@5.0.0` ship `LICENSE.md` v1.0 (a pointer to [license.desertant.com/1.0](https://license.desertant.com/1.0)), and the site is at v1.1 (30 October 2026). VeilFS relies on [v1.1](https://license.desertant.com/1.1.txt) because it describes the license check the 5.0.0 SDK makes, while [v1.0](https://license.desertant.com/1.0.txt) only describes usage "telemetry" that counts monthly active devices.

**Credit.** A "Powered by Desert Ant Labs" credit linking to [desertant.com](https://desertant.com) is in the app sidebar footer now.
