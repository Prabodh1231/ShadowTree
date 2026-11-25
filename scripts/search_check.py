r"""Real-model search check: index a fresh sample folder into a scratch DB, run 9 queries.

Usage (PowerShell, from the repo root):
  backend\.venv\Scripts\python.exe scripts\search_check.py

Samples go to %TEMP%\st-fix2\samples and the DB to %TEMP%\st-fix2\scratch.db (both outside
the repo and outside the scanned folder). Needs the models from scripts\download_models.py.
Runs in-process (no port, no network). Prints, per query, the strong results and the weak
list with match and the parts: z, cos, bm25, boost.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.gettempdir()) / "st-fix2"
QUERIES = ["tax documents", "volcano penguin", "invoice", "money I spent",
           "pay the bill", "my diary", "coffee", "error message", "meeting"]


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_samples.py"), str(WORK / "samples")],
                   check=True, stdout=subprocess.DEVNULL)
    root = WORK / "samples" / "sample_messy_folder"
    os.environ["VEILFS_DB_PATH"] = str(WORK / "scratch.db")
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, str(REPO / "backend"))
    from fastapi.testclient import TestClient

    from app import jobs, search
    from app.main import app

    with TestClient(app, base_url="http://127.0.0.1:8012") as client:
        r = client.post("/scan", json={"root": str(root)})
        r.raise_for_status()
        jobs.wait_idle(600)
        st = client.get("/scan/status").json()
        print("scan:", st["state"], st.get("stats"))
        from app import db
        conn = db.get_conn()
        for q in QUERIES:
            ranked, info = search.score_all(conn, q)
            print(f"\n== {q!r}  rerank={info['rerank']}")
            for t in ranked[:6]:
                tag = "STRONG" if t["match"] >= search.MIN_MATCH else "weak  "
                z = "None" if t["z"] is None else f"{t['z']:.2f}"
                c = "None" if t["cos"] is None else f"{t['cos']:.3f}"
                print(f"  {tag} {t['match']:3d}%  z={z:>6} cos={c:>6} bm25={t['bm25']:.2f} "
                      f"boost={t['boost']:2d}  {t['row']['name']}")
            body = search.search(conn, q)
            print("  results:", [x["name"] for x in body["results"]], "weak:", [x["name"] for x in body["weak"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
