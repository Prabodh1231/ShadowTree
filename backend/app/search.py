"""Search: FTS5 BM25 prefilter, GLiClass rerank, blended `match` percentage.

Final formula (documented in docs/review/phase-1.md):
  score      = raw GLiClass score for the query as the only label (0..1)
  bm25_norm  = 0..1 across the FTS hits (1 = best hit); 0 for non-FTS candidates
  match      = round(100 * (0.7 * score / max(top_score, 0.15) + 0.3 * bm25_norm)), clamped 0..100
  no rerank  = round(100 * bm25_norm), results limited to FTS hits, `rerank: false`
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


def search(conn, q: str) -> dict:
    cfg = get_settings()
    hits = fts_hits(conn, q, cfg.search_fts_limit)
    norm = dict(hits)
    ids = [i for i, _ in hits]
    if len(ids) < cfg.search_min_hits:  # too few: add the most recent files, capped
        have = set(ids)
        recent = conn.execute("SELECT id FROM files ORDER BY indexed_at DESC, id DESC LIMIT ?",
                              (cfg.search_fallback_cap + len(have),)).fetchall()
        ids += [r["id"] for r in recent if r["id"] not in have][: cfg.search_fallback_cap]
    if not ids:
        return {"query": q, "rerank": False, "results": []}
    rows = {r["id"]: r for r in conn.execute(
        "SELECT * FROM files WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)}
    ids = [i for i in ids if i in rows]

    scores: dict[int, float] | None = None
    try:
        texts = [ai_classify.classifier_text(rows[i]["title"] or "", rows[i]["summary"] or "",
                                             json.loads(rows[i]["keywords"] or "[]"),
                                             rows[i]["text_excerpt"] or "") for i in ids]
        scores = dict(zip(ids, ai_classify.rerank(q, texts)))
    except Exception:  # missing, failing or busy GLiClass: BM25 only
        scores = None

    ranked: list[tuple[int, int, float | None]] = []
    if scores is None:
        for i in ids:
            if i in norm:
                ranked.append((i, round(100 * norm[i]), None))
    else:
        top = max(scores.values(), default=0.0)
        for i in ids:
            m = W_SCORE * scores[i] / max(top, TOP_FLOOR) + W_BM25 * norm.get(i, 0.0)
            ranked.append((i, max(0, min(100, round(100 * m))), scores[i]))
    ranked.sort(key=lambda t: (-t[1], -(t[2] or 0.0)))
    ranked = ranked[:MAX_RESULTS]
    cards = {c["id"]: c for c in db.file_cards(conn, [rows[i] for i, _, _ in ranked])}
    results = []
    for i, match, score in ranked:
        results.append({**cards[i], "score": score, "match": match})
    return {"query": q, "rerank": scores is not None, "results": results}
