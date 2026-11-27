"""Hardening fixes from the code review, through the API: access token, one backend per data
folder, server-side PII baseline, lighter lists, scan cancel, capped errors, preview cache, clearing
the index."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from app import extractors

from conftest import run_scan

BACKEND = Path(__file__).resolve().parents[1]


# ---- access token -------------------------------------------------------------------

def test_requests_need_the_token(client):
    assert client.get("/files", headers={"Authorization": ""}).status_code == 401
    assert client.get("/files", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/open", json={"file_id": 1}, headers={"Authorization": ""}).status_code == 401
    assert client.get("/files/1/preview", headers={"Authorization": ""}).status_code == 401
    assert client.get("/export/snapshot", headers={"Authorization": ""}).status_code == 401
    assert client.get("/files").status_code == 200          # the fixture sends the right token
    assert client.get("/health", headers={"Authorization": ""}).status_code == 200  # the shell's probe


def test_401_keeps_cors_headers_and_preflight_allows_the_header(client):
    r = client.get("/files", headers={"Authorization": "", "origin": "http://tauri.localhost"})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == "http://tauri.localhost"
    pre = client.options("/files", headers={"origin": "http://tauri.localhost", "access-control-request-method": "GET",
                                            "access-control-request-headers": "authorization"})
    assert pre.status_code == 200 and "authorization" in pre.headers["access-control-allow-headers"].lower()


def test_generated_token_is_random_and_stable(monkeypatch):
    from app import config
    monkeypatch.delenv(config.TOKEN_ENV, raising=False)
    monkeypatch.setattr(config, "_generated_token", None)
    t = config.api_token()
    assert len(t) >= 32 and config.api_token() == t and not config.token_from_env()
    monkeypatch.setenv(config.TOKEN_ENV, "from-shell")
    assert config.api_token() == "from-shell" and config.token_from_env()


_TRY_LOCK = ("import sys; from pathlib import Path; from app import instance\n"
             "try:\n    instance.acquire(Path(sys.argv[1]))\nexcept instance.AlreadyRunning:\n    sys.exit(3)\n")


def test_second_backend_on_the_same_data_folder_is_refused(tmp_path):
    from app import instance
    instance.acquire(tmp_path)
    try:
        r = subprocess.run([sys.executable, "-c", _TRY_LOCK, str(tmp_path)], cwd=str(BACKEND))
        assert r.returncode == 3
    finally:
        instance.release()
    r = subprocess.run([sys.executable, "-c", _TRY_LOCK, str(tmp_path)], cwd=str(BACKEND))
    assert r.returncode == 0                                 # free again once released


# ---- server-side personal-data baseline -------------------------------------------------

def test_detect_pii_finds_the_high_precision_types():
    d = extractors.detect_pii
    assert d("write to billing@example.com") == ["EMAIL"]
    assert d("Contact: +1 555-0142") == ["PHONE"]
    assert d("Phone: (555) 012-3456") == ["PHONE"]
    assert d("card 4111 1111 1111 1111 exp 12/29") == ["CREDIT_CARD"]
    assert d("IBAN GB82 WEST 1234 5698 7654 32") == ["BANK_ACCOUNT"]
    assert d("SSN 123-45-6789") == ["SSN"]


def test_detect_pii_ignores_numbers_that_are_not_personal():
    d = extractors.detect_pii
    assert d("Invoice INV-2041, total $960.00, due 2026-11-20 10:30") == []
    assert d("Years 2024 2025 2026 and order 1234 5678") == []
    assert d("card 4111 1111 1111 1112") == []                 # fails the Luhn check
    assert d("GB82 WEST 1234 5698 7654 33") == []              # fails the IBAN check
    assert d("version 1.2.3, port 8000, 0000-00-0000") == []


def test_server_flag_puts_a_file_in_sensitive_and_the_browser_cannot_clear_it(client, sample_root):
    run_scan(client, sample_root)
    cards = {c["name"]: c for c in client.get("/files").json()}
    inv = cards["invoice.txt"]
    assert set(inv["server_pii"]) >= {"EMAIL", "PHONE"} and cards["diary.md"]["server_pii"] == []
    r = client.patch(f"/files/{inv['id']}/client-meta", json={"sha256": inv["sha256"], "has_pii": False})
    assert r.status_code == 200
    sens = next(f for f in client.get("/folders").json() if f["name"] == "Sensitive (PII)")
    assert sens["file_count"] == 1
    assert [c["id"] for c in client.get("/files", params={"folder_id": sens["id"]}).json()] == [inv["id"]]


def test_old_rows_get_the_server_check_on_start(client, sample_root):
    from app import db
    run_scan(client, sample_root)
    conn = db.get_conn()
    conn.execute("UPDATE files SET server_pii=NULL")
    conn.commit()
    assert db.backfill_server_pii(conn) == 4
    inv = conn.execute("SELECT server_pii FROM files WHERE name='invoice.txt'").fetchone()[0]
    assert "EMAIL" in inv


def test_lists_leave_out_the_redacted_excerpt(client, sample_root):
    run_scan(client, sample_root)
    c = next(c for c in client.get("/files").json() if c["name"] == "diary.md")
    body = {"sha256": c["sha256"], "has_pii": False, "redacted_excerpt": "Dear diary " * 100}
    assert client.patch(f"/files/{c['id']}/client-meta", json=body).status_code == 200
    listed = next(x for x in client.get("/files").json() if x["id"] == c["id"])
    assert "redacted_excerpt" not in listed["client_meta"] and listed["client_meta"]["sha256"] == c["sha256"]
    assert client.get(f"/files/{c['id']}").json()["client_meta"]["redacted_excerpt"].startswith("Dear diary")


# ---- jobs: cancel, capped errors ----------------------------------------------------------

def test_cancel_stops_a_scan_after_the_current_file(client, tmp_path, monkeypatch):
    from app import ai_cactus, jobs
    root = tmp_path / "many"
    root.mkdir()
    for i in range(12):
        (root / f"note{i:02}.txt").write_text(f"Note number {i} about the garden and the weather.", encoding="utf-8")
    real = ai_cactus.structured
    monkeypatch.setattr(ai_cactus, "structured", lambda text: (time.sleep(0.25), real(text))[1])
    assert client.post("/scan", json={"root": str(root)}).status_code == 200
    deadline = time.time() + 20
    while client.get("/scan/status").json()["processed"] < 1 and time.time() < deadline:
        time.sleep(0.05)
    assert client.post("/scan/cancel").json() == {"cancelled": True}
    assert jobs.wait_idle(30)
    s = client.get("/scan/status").json()
    assert s["state"] == "cancelled" and s["processed"] < 12
    assert 1 <= len(client.get("/files").json()) < 12          # what was read stays
    assert client.post("/scan/cancel").json() == {"cancelled": False}   # nothing runs now


def test_scan_errors_are_capped():
    from app import scanner
    errors: list[str] = []
    for i in range(scanner.MAX_ERRORS + 50):
        scanner.add_error(errors, f"e{i}")
    assert len(errors) == scanner.MAX_ERRORS + 1 and errors[-1] == scanner.MORE_ERRORS


# ---- preview cache ------------------------------------------------------------------------

def test_preview_cache_is_bounded_by_bytes():
    from app.previews import PreviewCache
    c = PreviewCache(max_bytes=1000)
    for i in range(10):
        c.put(i, b"x" * 300)
    assert c.size_bytes <= 1000 and len(c) == 3 and c.get(9) is not None and c.get(0) is None
    c.put("fail", b"")
    assert c.get("fail") == b""                                # a failed render is remembered
    c.put("huge", b"x" * 5000)
    assert c.get("huge") is None                               # bigger than the whole budget: not kept


# ---- clearing the index ---------------------------------------------------------------------

def test_clear_index_forgets_every_file_but_keeps_folders(client, sample_root):
    from app import db
    run_scan(client, sample_root)
    folders_before = [f["name"] for f in client.get("/folders").json()]
    r = client.post("/index/clear")
    assert r.status_code == 200 and r.json() == {"removed": 4}
    assert client.get("/files").json() == []
    assert [f["name"] for f in client.get("/folders").json()] == folders_before
    assert client.get("/search", params={"q": "invoice"}).json()["results"] == []
    conn = db.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM file_folder_links").fetchone()[0] == 0
    assert all(sample_root.joinpath(n).exists() for n in ("invoice.txt", "shot.png", "voice.wav"))
    run_scan(client, sample_root)                              # and it indexes again from scratch
    assert len(client.get("/files").json()) == 4


def test_clear_index_is_refused_while_a_job_runs(client, monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "is_running", lambda: True)
    assert client.post("/index/clear").status_code == 409
