"""Step 3 run: real DeBERTa scores for every sample file x topic folder, the links written,
and the "Bills to pay" new-folder cosine pre-filter. Fresh temp DB, offline, samples read-only.

  backend\\.venv\\Scripts\\python.exe spikes\\step3_tune.py <sample_folder> <temp_db_path> [--no-scan]
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sample, dbp = Path(sys.argv[1]), Path(sys.argv[2])
os.environ["VEILFS_DB_PATH"] = str(dbp)
from app.config import apply_env, get_settings  # noqa: E402

apply_env()
from app import ai_cactus, ai_classify, ai_embed, db, scanner  # noqa: E402

db.init_db()
conn = db.get_conn()
if "--no-scan" not in sys.argv:
    t0 = time.perf_counter()
    errs: list[str] = []
    print("scan", scanner.scan(sample, lambda **k: None, errs), f"{time.perf_counter() - t0:.1f}s", errs[:3])
    ai_cactus.close()

topics = [f for f in scanner.classifiable_folders(conn) if f[1] != db.MEDIA]
labels = ai_classify.unique_labels(topics)
print("\nhypotheses:")
for _, h in labels:
    print("  ", h)
rows = conn.execute("SELECT * FROM files ORDER BY name").fetchall()
short = [n.split(" ")[0] for _, n, _ in topics]
print("\n| file | " + " | ".join(n for _, n, _ in topics) + " | links |")
t_all = 0.0
for r in rows:
    text = ai_classify.classifier_text(r["title"] or "", r["summary"] or "", json.loads(r["keywords"]), r["text_excerpt"] or "")
    t0 = time.perf_counter()
    s = ai_classify.classify(text, [l for _, l in labels])
    t_all += time.perf_counter() - t0
    links = [l["name"] for l in conn.execute(
        "SELECT v.name FROM file_folder_links k JOIN virtual_folders v ON v.id=k.folder_id WHERE k.file_id=? ORDER BY v.id", (r["id"],))]
    print(f"| {r['name']} | " + " | ".join(f"{x:.3f}" for x in s) + f" | {', '.join(links)} |")
print(f"\nclassify time for {len(rows)} files x {len(labels)} folders: {t_all:.2f}s")

# new folder
name, desc = "Bills to pay", "invoices, bills and payments that are due"
if not conn.execute("SELECT 1 FROM virtual_folders WHERE name=?", (name,)).fetchone():
    cur = conn.execute("INSERT INTO virtual_folders(name, emoji, description, kind) VALUES (?,?,?, 'custom')", (name, "x", desc))
    conn.commit()
    fid = cur.lastrowid
    t0 = time.perf_counter()
    errs = []
    st = scanner.link_new_folders([fid], lambda **k: None, errs)
    print("\nnew folder job:", st, f"{time.perf_counter() - t0:.2f}s", errs[:3])
fid = conn.execute("SELECT id FROM virtual_folders WHERE name=?", (name,)).fetchone()["id"]
fv = ai_embed.embed([f"{name}. {desc}"])[0]
h = ai_classify.hypothesis(name, desc)
thr = get_settings().newfolder_cosine
print(f"\n| file | cosine (pre-filter >= {thr}) | DeBERTa '{h}' | linked |")
for r in rows:
    c = float(ai_embed.from_blob(r["vec"]) @ fv)
    text = ai_classify.classifier_text(r["title"] or "", r["summary"] or "", json.loads(r["keywords"]), r["text_excerpt"] or "")
    s = ai_classify.classify(text, [h])[0]
    linked = bool(conn.execute("SELECT 1 FROM file_folder_links WHERE file_id=? AND folder_id=?", (r["id"], fid)).fetchone())
    print(f"| {r['name']} | {c:.3f} | {s:.3f} | {'yes' if linked else 'no'} |")
