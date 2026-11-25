"""Search: FTS5 BM25 + potion cosine candidates, FlashRank rerank, one documented `match` percentage.

Pipeline
  1. candidates = FTS5 hits (at most 40) + the 50 files with the highest cosine between the
     query vector and the stored files.vec (potion). With no query vector (model missing):
     FTS hits + 20 recent files, as before.
  2. FlashRank scores query vs the same passage text that was embedded
     (title + summary + keywords + first 300 chars). ai_classify.rerank returns the raw logit z.
  3. match (0..100), see `match_percent`. Weights of the parts that exist are renormalised
     (each mix is divided by the sum of the weights it uses):
        confident (best z >= Z_USEFUL = -6, i.e. the reranker found a real match):
            mix = 0.6 * sigmoid((z + 4) / 2) + 0.3 * min(cos / 0.6, 1) + 0.1 * bm25_norm
        otherwise (reranker sees only noise, z about -11 for every file):
            semantic-only mix = min(cos / 0.35, 1); with FTS hits, bm25_norm joins at weight 0.3
            against 0.7 for the cosine part
        match = round(100 * mix) + name boost (+20 when every query word is in the name/title)
  4. Results need match >= MIN_MATCH. If none do, `results` is [] and `weak` holds the top 3.
  Fallbacks: no FlashRank folder -> cosine order, match from cosine alone (`rerank: false`,
  `note` explains); no vectors either -> BM25 only. Nothing here downloads a model.
shortcut: cosine is a numpy scan over all stored vectors (fine to a few 10k files); upgrade
to an ANN index beyond that.
"""
from __future__ import annotations

import math
import re

import numpy as np

from . import ai_classify, ai_embed, db
from .extractors import STOPWORDS

MAX_RESULTS = 50
MIN_MATCH = 25
NAME_BOOST = 20
FTS_LIMIT, RECENT_LIMIT, COS_LIMIT, BATCH = 40, 20, 50, 16
WEAK_COUNT = 3
# match formula constants, tuned on the sample folder (see reports/shadowtree/step2.md)
Z_MID, Z_SCALE = -4.0, 2.0
REL_W, COS_W, BM25_W = 0.6, 0.3, 0.1
Z_USEFUL = -6.0   # best z at or above this: the reranker found a real match
COS_FULL = 0.35   # semantic-only mode: cosine 0.35 counts as 100%


def build_match(q: str) -> str | None:
    """Quote every token so INV-2041, a lone quote, NEAR or a:b cannot break FTS syntax.
    Tokens are OR-ed, with a prefix match. Returns None when nothing is searchable."""
    toks = re.findall(r"\w+", q, re.UNICODE)
    keep = [t for t in toks if len(t) > 1 and t.lower() not in STOPWORDS] or [t for t in toks if t]
    if not keep:
        return None
    return " OR ".join('"%s"*' % t.replace('"', '""') for t in keep[:12])


def fts_hits(conn, q: str, limit: int) -> list[tuple[int, float]]:
    """[(file_id, bm25_norm)] best first."""
    m = build_match(q)
    if not m:
        return []
    rows = conn.execute(
        "SELECT rowid AS id, bm25(files_fts) AS b FROM files_fts WHERE files_fts MATCH ? ORDER BY b LIMIT ?",
        (m, limit)).fetchall()
    if not rows:
        return []
    vals = [-r["b"] for r in rows]          # flip: higher = better
    lo, hi = min(vals), max(vals)
    return [(r["id"], 1.0 if hi == lo else (v - lo) / (hi - lo)) for r, v in zip(rows, vals)]


def name_boost(q: str, name: str, title: str) -> int:
    """+20 when every non-stopword query token is a prefix of a word in the file name or title."""
    toks = [t.lower() for t in re.findall(r"\w+", q, re.UNICODE) if t.lower() not in STOPWORDS]
    if not toks:
        return 0
    words = re.findall(r"\w+", f"{name} {title}".lower(), re.UNICODE)
    return NAME_BOOST if all(any(w.startswith(t) for w in words) for t in toks) else 0


def cosine_top(conn, qvec: np.ndarray, limit: int) -> dict[int, float]:
    """{file_id: cosine} for the `limit` stored vectors closest to qvec (unit vectors: a dot product)."""
    # a blob of another length (older model, corrupt row) is skipped, not allowed to break np.stack
    rows = [r for r in conn.execute("SELECT id, vec FROM files WHERE vec IS NOT NULL")
            if len(r["vec"]) == ai_embed.DIM * 4]
    if not rows:
        return {}
    ids = [r["id"] for r in rows]
    mat = np.stack([ai_embed.from_blob(r["vec"]) for r in rows])
    sims = mat @ qvec
    order = np.argsort(-sims)[:limit]
    return {ids[i]: float(sims[i]) for i in order}


def _rerank_batches(q: str, texts: list[str]) -> list[float]:
    """Rerank in batches of BATCH. ai_classify.rerank takes and releases the model lock per
    call, so a running scan can get the lock between batches.
    shortcut: a search may mix batches if a scan runs between them; fine for a local
    single-user app. Upgrade: hold the lock for the whole search."""
    out: list[float] = []
    for i in range(0, len(texts), BATCH):
        out += ai_classify.rerank(q, texts[i:i + BATCH])
    return out


def match_percent(z: float | None, cos: float | None, bm25: float, has_fts: bool, confident: bool) -> int:
    """0..100 before the name boost. Weights of the parts that exist are renormalised.
    confident: the reranker found a real match for this query (best z >= Z_USEFUL), so its
    sigmoid(z) is trusted. Otherwise it only sees noise (z near -11 for every file; TinyBERT
    is mostly lexical) and the potion cosine carries the match, scaled so 0.35 = 100%."""
    parts: list[tuple[float, float]] = []
    if z is not None and confident:
        parts.append((REL_W, 1.0 / (1.0 + math.exp(-(z - Z_MID) / Z_SCALE))))
        if cos is not None:
            parts.append((COS_W, min(1.0, max(0.0, cos / 0.6))))
    elif cos is not None:
        parts.append((0.7, min(1.0, max(0.0, cos / COS_FULL))))
    if has_fts:
        parts.append((BM25_W if confident else 0.3, bm25))
    if not parts:
        return 0
    w = sum(p[0] for p in parts)
    return round(100 * sum(p[0] * p[1] for p in parts) / w)


def score_all(conn, q: str, cand_limit: int | None = None) -> tuple[list[dict], dict]:
    """Candidates with their parts. Returns (rows, info). `cand_limit` None: the normal limits."""
    hits = fts_hits(conn, q, FTS_LIMIT)
    norm = dict(hits)
    qvec = None
    try:
        qvec = ai_embed.embed([q], wait=2.0)[0]
    except Exception:  # model missing or busy: text search only
        qvec = None
    cos = cosine_top(conn, qvec, COS_LIMIT if cand_limit is None else cand_limit) if qvec is not None else {}
    ids = [i for i, _ in hits]
    ids += [i for i in cos if i not in norm]
    if qvec is None:
        have = set(ids)
        recent = conn.execute("SELECT id FROM files ORDER BY indexed_at DESC, id DESC LIMIT ?",
                              (RECENT_LIMIT + len(have),)).fetchall()
        ids += [r["id"] for r in recent if r["id"] not in have][:RECENT_LIMIT]
    if not ids:
        return [], {"vec": qvec is not None, "rerank": False, "note": None}
    rows = {r["id"]: r for r in conn.execute(
        "SELECT * FROM files WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)}
    ids = [i for i in ids if i in rows]
    if qvec is not None:  # cosine for FTS hits that were not in the top list
        for i in ids:
            if i not in cos and rows[i]["vec"] is not None and len(rows[i]["vec"]) == ai_embed.DIM * 4:
                cos[i] = float(ai_embed.from_blob(rows[i]["vec"]) @ qvec)

    z: dict[int, float] | None
    note = None
    try:
        texts = [ai_embed.passage_text(rows[i]["title"], rows[i]["summary"], rows[i]["keywords"],
                                       rows[i]["text_excerpt"]) for i in ids]
        z = dict(zip(ids, _rerank_batches(q, texts)))
    except Exception as exc:
        z = None
        note = ("Ranking by meaning only: the re-ranker is not available (%s)" % exc) if qvec is not None \
            else "Plain text search only: the search models are not available"
    confident = bool(z) and max(z.values()) >= Z_USEFUL
    out = []
    for i in ids:
        r = rows[i]
        boost = name_boost(q, r["name"] or "", r["title"] or "")
        zi, ci, bi = (z[i] if z else None), cos.get(i), norm.get(i, 0.0)
        if z is None and ci is None and i not in norm:
            continue                                   # BM25-only mode: FTS hits only
        m = match_percent(zi, ci, bi, bool(norm), confident)
        out.append({"id": i, "row": r, "z": zi, "cos": ci, "bm25": bi, "boost": boost,
                    "match": max(0, min(100, m + boost))})
    out.sort(key=lambda t: (-t["match"], -(t["z"] if t["z"] is not None else -99.0), -(t["cos"] or 0.0)))
    return out, {"vec": qvec is not None, "rerank": z is not None, "confident": confident, "note": note}


def search(conn, q: str) -> dict:
    ranked, info = score_all(conn, q)
    strong = [t for t in ranked if t["match"] >= MIN_MATCH][:MAX_RESULTS]
    weak = [] if strong else ranked[:WEAK_COUNT]
    cards = {c["id"]: c for c in db.file_cards(conn, [t["row"] for t in strong + weak])}

    def shape(t):
        return {**cards[t["id"]], "score": t["z"], "match": t["match"]}
    res = {"query": q, "rerank": info["rerank"],
           "results": [shape(t) for t in strong], "weak": [shape(t) for t in weak]}
    if info["note"]:
        res["note"] = info["note"]
    return res
