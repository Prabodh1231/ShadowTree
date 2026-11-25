"""Search: FTS5 BM25 prefilter, reranker rerank, blended `match` percentage.

Final formula (documented in docs/review/phase-1.md):
  score      = raw reranker score for the query as the only label (0..1)
  bm25_norm  = 0..1 across the FTS hits (1 = best hit); 0 for non-FTS candidates
  match      = round(100 * (0.7 * score / max(top_score, 0.15) + 0.3 * bm25_norm)) + boost, clamped 0..100
  (no FTS hit at all: weights 1.0 / 0.0, so the best semantic hit shows 100)
  boost      = +20 when every non-stopword query token (prefix ok) is in the file name or title
  no rerank  = round(100 * bm25_norm) + boost, results limited to FTS hits, `rerank: false`
Results need match >= MIN_MATCH (35). If none do, `results` is [] and `weak` holds the top 3
below the cut-off. `weak` is always present and is [] when `results` is not empty.
Candidates: at most 40 FTS hits plus 20 recent files, reranked in batches of 16.
bm25() is lower-is-better (negative), so it is flipped before normalising.
"""
from __future__ import annotations

import json
import re

from . import ai_classify, db
from .config import get_settings
from .extractors import STOPWORDS

W_SCORE, W_BM25, TOP_FLOOR = 0.7, 0.3, 0.15
MAX_RESULTS = 50
MIN_MATCH = 35
NAME_BOOST = 20
FTS_LIMIT, RECENT_LIMIT, BATCH = 40, 20, 16
WEAK_COUNT = 3


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


def _rerank_batches(q: str, texts: list[str]) -> list[float]:
    """Rerank in batches of BATCH. ai_classify.rerank takes and releases the model lock per
    call, so a running scan can get the lock between batches.
    shortcut: a search may mix batches if a scan runs between them (the model lock is free
    in between and the files may change); fine for a local single-user app. Upgrade: hold
    the lock for the whole search."""
    out: list[float] = []
    for i in range(0, len(texts), BATCH):
        out += ai_classify.rerank(q, texts[i:i + BATCH])
    return out


def search(conn, q: str) -> dict:
    hits = fts_hits(conn, q, FTS_LIMIT)
    norm = dict(hits)
    ids = [i for i, _ in hits]
    have = set(ids)  # always add the most recent files so a purely semantic match can surface
    recent = conn.execute("SELECT id FROM files ORDER BY indexed_at DESC, id DESC LIMIT ?",
                          (RECENT_LIMIT + len(have),)).fetchall()
    ids += [r["id"] for r in recent if r["id"] not in have][:RECENT_LIMIT]
    if not ids:
        return {"query": q, "rerank": False, "results": [], "weak": []}
    rows = {r["id"]: r for r in conn.execute(
        "SELECT * FROM files WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)}
    ids = [i for i in ids if i in rows]

    scores: dict[int, float] | None = None
    try:
        texts = [ai_classify.classifier_text(rows[i]["title"] or "", rows[i]["summary"] or "",
                                             json.loads(rows[i]["keywords"] or "[]"),
                                             rows[i]["text_excerpt"] or "") for i in ids]
        scores = dict(zip(ids, _rerank_batches(q, texts)))
    except Exception:  # missing, failing or busy reranker: BM25 only
        scores = None

    boost = {i: name_boost(q, rows[i]["name"] or "", rows[i]["title"] or "") for i in ids}
    ranked: list[tuple[int, int, float | None]] = []
    if scores is None:
        for i in ids:
            if i in norm:
                ranked.append((i, max(0, min(100, round(100 * norm[i]) + boost[i])), None))
    else:
        top = max(scores.values(), default=0.0)
        w_score, w_bm25 = (W_SCORE, W_BM25) if norm else (1.0, 0.0)  # no FTS hit: score only
        for i in ids:
            m = w_score * scores[i] / max(top, TOP_FLOOR) + w_bm25 * norm.get(i, 0.0)
            ranked.append((i, max(0, min(100, round(100 * m) + boost[i])), scores[i]))
    ranked.sort(key=lambda t: (-t[1], -(t[2] or 0.0)))
    strong = [t for t in ranked if t[1] >= MIN_MATCH][:MAX_RESULTS]
    weak = [] if strong else ranked[:WEAK_COUNT]
    cards = {c["id"]: c for c in db.file_cards(conn, [rows[i] for i, _, _ in strong + weak])}

    def shape(t):
        return {**cards[t[0]], "score": t[2], "match": t[1]}
    return {"query": q, "rerank": scores is not None,
            "results": [shape(t) for t in strong], "weak": [shape(t) for t in weak]}