"""Soft floor: a file that no topic folder claims at 0.5 still gets its single best topic folder."""
from conftest import run_scan

from app import ai_classify, db, jobs


def _links(name):
    return [(r["name"], r["score"]) for r in db.get_conn().execute(
        "SELECT v.name, l.score FROM file_folder_links l JOIN virtual_folders v ON v.id=l.folder_id "
        "JOIN files f ON f.id=l.file_id WHERE f.name=?", (name,))]


def _scores(best, rest=0.05):
    return lambda t, labels: [best] + [rest] * (len(labels) - 1)


def test_best_score_above_floor_gives_one_soft_link(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", _scores(0.3))
    run_scan(client, sample_root)
    links = _links("invoice.txt")
    assert len(links) == 1 and links[0][0] != db.UNSORTED and abs(links[0][1] - 0.3) < 1e-6


def test_best_score_below_floor_is_unsorted(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", _scores(0.14))
    run_scan(client, sample_root)
    assert _links("invoice.txt") == [(db.UNSORTED, 0.0)]


def test_strong_match_keeps_strict_rule_and_no_soft_link(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", lambda t, labels: [0.9, 0.3] + [0.05] * (len(labels) - 2))
    run_scan(client, sample_root)
    assert len(_links("invoice.txt")) == 1


def test_new_folder_job_does_not_link_a_weak_file(client, sample_root, monkeypatch):
    monkeypatch.setattr(ai_classify, "classify", _scores(0.05))
    run_scan(client, sample_root)
    monkeypatch.setattr(ai_classify, "classify", lambda t, labels: [0.3] * len(labels))
    before = {(r["file_id"], r["folder_id"]) for r in db.get_conn().execute("SELECT * FROM file_folder_links")}
    client.post("/folders", json={"name": "Anything", "description": ""})
    assert jobs.wait_idle(60)
    after = {(r["file_id"], r["folder_id"]) for r in db.get_conn().execute("SELECT * FROM file_folder_links")}
    assert after == before
