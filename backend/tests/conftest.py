"""Test setup: temp DB, every model mocked, non-loopback sockets blocked."""
from __future__ import annotations

import socket
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import numpy as np

from app import ai_cactus, ai_classify, ai_embed, ai_ocr, db, jobs

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def block_external_sockets(monkeypatch):
    real = socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if self.family != getattr(socket, "AF_UNIX", -1) and host not in LOOPBACK:
            raise AssertionError(f"test tried a non-loopback connection to {host!r}")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guard)


class Calls:
    def __init__(self):
        self.structured = 0
        self.describe = 0
        self.transcribe = 0
        self.classify = 0


@pytest.fixture
def calls(monkeypatch):
    c = Calls()

    def structured(text):
        c.structured += 1
        first = text.strip().splitlines()[0][:40] if text.strip() else "Doc"
        return {"title": first, "summary": "A model written summary of the file text.", "keywords": ["alpha", "beta"]}

    def describe(path):
        c.describe += 1
        return "screenshot image\nMonthly Budget\nGroceries $120.50"

    def transcribe(path):
        c.transcribe += 1
        return "Please pay the electricity invoice before Friday."

    def classify(text, labels):
        c.classify += 1
        t = text.lower()
        out = []
        for l in labels:
            if "invoices" in l and "invoice" in t:
                out.append(0.9)
            elif "journal" in l and "diary" in t:
                out.append(0.8)
            else:
                out.append(0.1)
        return out

    monkeypatch.setattr(ai_cactus, "structured", structured)
    monkeypatch.setattr(ai_cactus, "describe_image", describe)
    monkeypatch.setattr(ai_cactus, "transcribe_audio", transcribe)
    monkeypatch.setattr(ai_classify, "classify", classify)
    monkeypatch.setattr(ai_classify, "rerank",
                        lambda q, passages, wait=None: [0.9 if "invoice" in p.lower() else 0.05 for p in passages])
    def embed(texts):
        """Fixed 256-d vectors: same text, same vector; no model."""
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, s in enumerate(texts):
            out[i, hash_slot(s)] = 1.0
        return out

    monkeypatch.setattr(ai_embed, "embed", embed)
    monkeypatch.setattr(ai_ocr, "ocr_image", lambda data: ["OCR line one", "OCR line two"])
    return c


def hash_slot(s: str) -> int:
    return sum(map(ord, s.lower())) % 256


@pytest.fixture
def client(tmp_path, monkeypatch, calls):
    data = tmp_path / "appdata"
    monkeypatch.setenv("VEILFS_DATA_DIR", str(data))
    monkeypatch.setenv("VEILFS_DB_PATH", str(data / "test.db"))
    db.close_thread_conns()
    from app.main import app
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c
    jobs.wait_idle(30)
    db.close_thread_conns()


def make_wav(path: Path, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * rate)


@pytest.fixture
def sample_root(tmp_path) -> Path:
    """A messy folder whose name has a space and an apostrophe."""
    from PIL import Image
    root = tmp_path / "Bob's messy files"
    (root / "sub dir").mkdir(parents=True)
    (root / "invoice.txt").write_text(
        "Invoice INV-2041 from Northwind Supplies.\nTotal due $960 by 15 December.\n"
        "Contact billing@example.com or +1 555-0142.", encoding="utf-8")
    (root / "sub dir" / "diary.md").write_text(
        "# Diary\n\nDear diary, today I walked by the lake with my dog and felt calm.", encoding="utf-8")
    Image.new("RGB", (64, 48), (200, 30, 30)).save(root / "shot.png")
    make_wav(root / "voice.wav")
    return root


def run_scan(client, root: Path) -> dict:
    r = client.post("/scan", json={"root": str(root)})
    assert r.status_code == 200, r.text
    assert jobs.wait_idle(60)
    return client.get("/scan/status").json()
