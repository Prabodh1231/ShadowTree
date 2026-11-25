"""Step 2 tuning run: index the sample folder with the real models into a temp DB, then print
every file's parts (cosine, FlashRank logit z, bm25, match) for the test queries and time
10 warm searches. Offline. Reads sample files read-only; writes only the temp DB.

  backend\\.venv\\Scripts\\python.exe spikes\\step2_tune.py <sample_folder> <temp_db_path> [--no-scan]
"""
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sample, dbp = Path(sys.argv[1]), Path(sys.argv[2])
os.environ["VEILFS_DB_PATH"] = str(dbp)
from app.config import apply_env  # noqa: E402

apply_env()
from app import ai_cactus, db, scanner, search  # noqa: E402

db.init_db()
conn = db.get_conn()
if "--no-scan" not in sys.argv:
    t0 = time.perf_counter()
    errs: list[str] = []
    stats = scanner.scan(sample, lambda **k: None, errs)
    print("scan", stats, f"{time.perf_counter() - t0:.1f}s", errs[:3])
    ai_cactus.close()

QUERIES = ["money I spent", "invoice", "meeting", "my diary", "volcano penguin"]
if len(sys.argv) > 3 and sys.argv[3] != "--no-scan":
    QUERIES = sys.argv[3:]
n_vec = conn.execute("SELECT count(*) c FROM files WHERE vec IS NOT NULL").fetchone()["c"]
print("files with vec:", n_vec, "of", conn.execute("SELECT count(*) c FROM files").fetchone()["c"])
for r in conn.execute("SELECT name, title, summary FROM files ORDER BY id"):
    print(f"  {r['name']!r}: title={r['title']!r} summary={(r['summary'] or '')[:90]!r}")
for q in QUERIES:
    rows, info = search.score_all(conn, q, cand_limit=100)
    print(f"\n== {q!r} {info}")
    for t in rows:
        z = "None" if t["z"] is None else f"{t['z']:7.2f}"
        c = "None" if t["cos"] is None else f"{t['cos']:5.2f}"
        print(f"  match={t['match']:3d}  z={z}  cos={c}  bm25={t['bm25']:.2f}  boost={t['boost']:2d}  {t['row']['name']}")
    res = search.search(conn, q)
    print("  -> results:", [(r['name'], r['match']) for r in res['results']], "weak:", [(r['name'], r['match']) for r in res['weak']])
times = []
for i in range(10):
    for q in QUERIES:
        t0 = time.perf_counter()
        search.search(conn, q)
        times.append(time.perf_counter() - t0)
print(f"\n{len(times)} warm searches: median {statistics.median(times) * 1000:.0f} ms, max {max(times) * 1000:.0f} ms")
