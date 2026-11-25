"""Step 3: DeBERTa NLI classifier seams, file-type rule, Unsorted fallback, re-link of old rows,
new-folder pre-filter + L4. No model: the real NLI path runs against a fake onnxruntime session."""
import json
import sys
import types

import numpy as np
import pytest
from conftest import run_scan

from app import ai_classify, ai_embed, db, jobs, scanner
from app.config import CLASSIFIER_VERSION


def _folders(card):
    return [f["name"] for f in card["folders"]]


def test_hypothesis_text():
    assert ai_classify.hypothesis("Bills", "due payments") == "This text is about Bills: due payments."
    assert ai_classify.hypothesis("Bills", "  ") == "This text is about Bills."
    assert ai_classify.hypothesis("Bills", None) == "This text is about Bills."
    assert ai_classify.unique_labels([(3, "Money", "bills or receipts")]) == [(3, "This text is about Money: bills or receipts.")]


def test_premise_uses_600_chars_of_text():
    t = ai_classify.classifier_text("T", "S", ["k"], "x" * 1000)
    assert t.count("x") == 600 and t.startswith("T. S Keywords: k.")


@pytest.fixture
def fake_deberta(tmp_path, monkeypatch):
    """A model folder with config.json, plus fake onnxruntime/tokenizers modules. id2label puts
    entailment at index 1 here, to prove the index is read from config.json (the real model uses 0)."""
    d = tmp_path / "models" / "deberta"
    (d / "onnx").mkdir(parents=True)
    (d / "onnx" / "model_quantized.onnx").write_bytes(b"x")
    (d / "tokenizer.json").write_text("{}")
    (d / "config.json").write_text(json.dumps({"id2label": {"0": "not_entailment", "1": "entailment"}}))
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path))
    seen = {}

    class Enc:
        def __init__(self, a, b):
            self.ids = [1] * (len(a.split()) + len(b.split()))
            self.attention_mask = [1] * len(self.ids)
            self.type_ids = [0] * len(self.ids)

    class Tok:
        @staticmethod
        def from_file(p):
            return Tok()

        def enable_truncation(self, max_length, strategy):
            seen["trunc"] = (max_length, strategy)

        def encode(self, a, b):
            seen.setdefault("pairs", []).append((a, b))
            return Enc(a, b)

    class Inp:
        def __init__(self, name):
            self.name = name

    class Sess:
        def __init__(self, path, so, providers):
            seen["threads"] = so.intra_op_num_threads

        def get_inputs(self):
            return [Inp("input_ids"), Inp("attention_mask")]   # no token_type_ids: must not be fed

        def run(self, _, feed):
            seen.setdefault("feeds", []).append(sorted(feed))
            yes = "Money" in seen["pairs"][-1][1]
            return [np.array([[0.0, 3.0]] if yes else [[3.0, 0.0]], dtype=np.float32)]

    class SO:
        intra_op_num_threads = 0
        enable_cpu_mem_arena = True

    ort = types.SimpleNamespace(SessionOptions=SO, InferenceSession=Sess)
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setitem(sys.modules, "tokenizers", types.SimpleNamespace(Tokenizer=Tok))
    monkeypatch.setenv("ONNX_THREADS", "3")
    ai_classify.close()
    yield seen
    ai_classify.close()
    sys.modules.pop("onnxruntime", None)
    sys.modules.pop("tokenizers", None)


def test_real_nli_path_reads_entailment_index_and_inputs(fake_deberta):
    from test_step1 import _ORIG
    s = _ORIG["classify"]("Coffee receipt total 7 dollars",
                          ["This text is about Money: bills.", "This text is about Diary."])
    assert s[0] == pytest.approx(1 / (1 + np.exp(-3)), rel=1e-5) and s[1] < 0.05   # softmax[entailment=1]
    assert fake_deberta["trunc"] == (384, "only_first") and fake_deberta["threads"] == 3
    assert all(f == ["attention_mask", "input_ids"] for f in fake_deberta["feeds"])
    assert fake_deberta["pairs"][0] == ("Coffee receipt total 7 dollars", "This text is about Money: bills.")


def test_missing_deberta_is_not_ready(tmp_path, monkeypatch):
    from test_step1 import _ORIG
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path))
    ai_classify.close()
    with pytest.raises(ai_classify.NotReady, match="not downloaded"):
        _ORIG["classify"]("t", ["h"])


def test_media_by_file_type_and_still_scored(client, sample_root, calls):
    run_scan(client, sample_root)
    cards = {c["name"]: c for c in client.get("/files").json()}
    assert _folders(cards["shot.png"]) == ["Screenshots & Media"]
    # voice.wav's transcript mentions an invoice: it gets Finance from the classifier AND Media by type
    assert set(_folders(cards["voice.wav"])) == {"Finance & Receipts", "Screenshots & Media"}
    assert "Screenshots & Media" not in _folders(cards["invoice.txt"])
    assert "Screenshots & Media" not in _folders(cards["diary.md"])


def test_media_folder_is_never_a_hypothesis(client, sample_root, monkeypatch):
    seen = []
    real = ai_classify.classify
    monkeypatch.setattr(ai_classify, "classify", lambda t, labels: seen.extend(labels) or real(t, labels))
    run_scan(client, sample_root)
    assert seen and not any("Screenshots" in l for l in seen)


def test_no_match_goes_to_unsorted_and_error_falls_back(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", lambda t, labels: [0.1] * len(labels))
    run_scan(client, sample_root)
    cards = {c["name"]: c for c in client.get("/files").json()}
    assert _folders(cards["invoice.txt"]) == ["Unsorted"]
    conn = db.get_conn()
    conn.execute("UPDATE files SET size=size+1")  # force a re-index of every file
    conn.commit()

    def boom(t, labels):
        raise RuntimeError("onnx exploded")
    monkeypatch.setattr(ai_classify, "classify", boom)
    (sample_root / "invoice.txt").write_text("Invoice changed text.", encoding="utf-8")
    run_scan(client, sample_root)
    inv = next(c for c in client.get("/files").json() if c["name"] == "invoice.txt")
    assert _folders(inv) == ["Unsorted"] and "onnx exploded" in (inv["ai_error"] or "")
    row = conn.execute("SELECT cls_ver FROM files WHERE name='invoice.txt'").fetchone()
    assert row["cls_ver"] is None                       # will be re-linked on the next scan


def test_old_classifier_rows_are_relinked_without_cactus(client, sample_root, calls):
    run_scan(client, sample_root)
    conn = db.get_conn()
    fin = db.folder_id("Finance & Receipts")
    work = db.folder_id("Work & Research")
    inv = conn.execute("SELECT id FROM files WHERE name='invoice.txt'").fetchone()["id"]
    # pretend GLiClass sorted it into Work and no version was stamped
    conn.execute("DELETE FROM file_folder_links WHERE file_id=?", (inv,))
    conn.execute("INSERT INTO file_folder_links VALUES (?,?,0.7)", (inv, work))
    conn.execute("UPDATE files SET cls_ver=NULL WHERE id=?", (inv,))
    conn.commit()
    before = (calls.structured, calls.describe, calls.transcribe)
    st = run_scan(client, sample_root)
    assert st["stats"]["skipped"] == 4                   # unchanged files: no re-hash, no Cactus
    assert (calls.structured, calls.describe, calls.transcribe) == before
    links = {r["folder_id"] for r in conn.execute("SELECT folder_id FROM file_folder_links WHERE file_id=?", (inv,))}
    assert links == {fin}
    assert conn.execute("SELECT count(*) c FROM files WHERE cls_ver IS NOT ?", (CLASSIFIER_VERSION,)).fetchone()["c"] == 0


def test_relink_keeps_old_links_when_classifier_is_not_ready(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    conn = db.get_conn()
    conn.execute("UPDATE files SET cls_ver=NULL")
    conn.commit()
    before = {tuple(r) for r in conn.execute("SELECT file_id, folder_id FROM file_folder_links")}

    def not_ready(t, labels):
        raise ai_classify.NotReady("no DeBERTa")
    monkeypatch.setattr(ai_classify, "classify", not_ready)
    run_scan(client, sample_root)
    assert {tuple(r) for r in conn.execute("SELECT file_id, folder_id FROM file_folder_links")} == before


def test_new_folder_prefilter_scores_only_close_files(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    scored = []

    def classify(text, labels):
        scored.append(text.split(".")[0])
        return [0.9] * len(labels)
    monkeypatch.setattr(ai_classify, "classify", classify)
    fv = {"Bills": None}

    def embed(texts, wait=None):
        # folder vector equals the stored vector of the invoice only (cosine 1 vs ~0 for others)
        conn = db.get_conn()
        v = conn.execute("SELECT vec FROM files WHERE name='invoice.txt'").fetchone()["vec"]
        fv["Bills"] = ai_embed.from_blob(v)
        return np.stack([fv["Bills"]] * len(texts))
    monkeypatch.setattr(ai_embed, "embed", embed)
    before = {(r["file_id"], r["folder_id"]) for r in db.get_conn().execute("SELECT * FROM file_folder_links")}
    fid = client.post("/folders", json={"name": "Bills", "description": "bills that are due"}).json()["folder_id"]
    assert jobs.wait_idle(60)
    conn = db.get_conn()
    after = {(r["file_id"], r["folder_id"]) for r in conn.execute("SELECT * FROM file_folder_links")}
    inv = conn.execute("SELECT id FROM files WHERE name='invoice.txt'").fetchone()["id"]
    assert after - before == {(inv, fid)}                 # only the new folder's link was written
    assert before <= after                                 # L4: nothing removed
    assert len(scored) == 1                                # only the close file reached DeBERTa


def test_new_folder_without_vectors_scores_everything(client, sample_root, monkeypatch):
    run_scan(client, sample_root)
    db.get_conn().execute("UPDATE files SET vec=NULL")
    db.get_conn().commit()
    n = []
    monkeypatch.setattr(ai_classify, "classify", lambda t, labels: n.append(1) or [0.1] * len(labels))
    client.post("/folders", json={"name": "Anything", "description": ""})
    assert jobs.wait_idle(60)
    assert len(n) == 4


def test_old_seed_descriptions_are_updated_but_user_edits_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILFS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VEILFS_DB_PATH", str(tmp_path / "s.db"))
    db.close_thread_conns()
    db.init_db()
    conn = db.get_conn()
    conn.execute("UPDATE virtual_folders SET description=? WHERE name='Finance & Receipts'",
                 (db.OLD_SEED_DESCRIPTIONS["Finance & Receipts"],))
    conn.execute("UPDATE virtual_folders SET description='my own words' WHERE name='Work & Research'")
    conn.commit()
    db.init_db()
    d = {r["name"]: r["description"] for r in conn.execute("SELECT name, description FROM virtual_folders")}
    assert d["Finance & Receipts"] == "money, payments, bills or receipts"
    assert d["Work & Research"] == "my own words"
    db.close_thread_conns()
