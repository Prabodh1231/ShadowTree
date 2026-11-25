"""Try seed folder descriptions against the indexed samples (temp DB from step3_tune.py). Offline."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ["VEILFS_DB_PATH"] = sys.argv[1]
from app.config import apply_env  # noqa: E402

apply_env()
from app import ai_classify, db  # noqa: E402

CANDS = {
    "Finance & Receipts": ["invoices, receipts, bills, payments and money spent",
                           "money: receipts, invoices, bills, bank transfers and payments"],
    "Work & Research": ["research, studies, experiments, meetings and work projects",
                        "a work meeting, a project plan or a research study",
                        "work and research: meetings, tasks, projects, studies and methods",
                        "jobs, meetings, projects, research questions and methods","work documents, meeting notes, projects and research",
                        "work, meetings, projects, research and study",
                        "work or research: meeting notes, project plans, research outlines and study notes"],
    "Personal & Notes": ["personal journal, diary, feelings and private notes",
                         "personal life, a diary or journal entry, feelings and everyday thoughts",
                         "someone's personal life, feelings or diary"],
}
rows = db.get_conn().execute("SELECT * FROM files ORDER BY name").fetchall()
texts = {r["name"]: ai_classify.classifier_text(r["title"] or "", r["summary"] or "", json.loads(r["keywords"]),
                                                r["text_excerpt"] or "") for r in rows}
for folder, descs in CANDS.items():
    for d in descs:
        h = ai_classify.hypothesis(folder, d)
        sc = {n: ai_classify.classify(t, [h])[0] for n, t in texts.items()}
        print(f"\n{folder} | {d}")
        print("   " + "  ".join(f"{n.split(' ')[0][:10]}={s:.2f}" for n, s in sc.items()))
