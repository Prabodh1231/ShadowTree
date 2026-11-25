"""Folder picker and quick-folder endpoints (the native dialog itself is mocked)."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

from app import picker


def test_pick_folder_returns_chosen_path(client, tmp_path, monkeypatch):
    ran = []

    def fake_run(args, **kw):
        ran.append((args, kw))
        return SimpleNamespace(stdout=str(tmp_path), returncode=0)

    monkeypatch.setattr("app.picker.subprocess.run", fake_run)
    r = client.post("/pick-folder", json={"initial": str(tmp_path)})
    assert r.status_code == 200 and r.json() == {"path": str(tmp_path)}
    args, kw = ran[0]
    assert args[1] == "-I" and args[-1] == str(tmp_path) and not kw.get("shell")


def test_pick_folder_cancel_and_missing_dir(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.picker.subprocess.run", lambda *a, **k: SimpleNamespace(stdout="", returncode=0))
    assert client.post("/pick-folder", json={}).json() == {"path": None}
    gone = str(tmp_path / "nope")
    monkeypatch.setattr("app.picker.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=gone, returncode=0))
    assert client.post("/pick-folder", json={}).json() == {"path": None}


def test_pick_folder_timeout_and_busy(client, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("python", 1)

    monkeypatch.setattr("app.picker.subprocess.run", boom)
    assert client.post("/pick-folder", json={}).json() == {"path": None}
    picker._lock.acquire()
    try:
        assert client.post("/pick-folder", json={}).status_code == 409
    finally:
        picker._lock.release()


def test_pick_folder_rejects_extra_fields(client):
    assert client.post("/pick-folder", json={"cmd": "x"}).status_code == 422


def test_quick_folders_only_existing(client):
    r = client.get("/quick-folders")
    assert r.status_code == 200
    for f in r.json()["folders"]:
        assert f["name"] in {"Documents", "Desktop", "Downloads", "Pictures"}
