"""Cactus wrappers (Mirage, Whistle, Needle 3) and the per-file card builder with fallbacks.

Rules enforced here:
- `cactus` is imported lazily inside functions, after config.apply_env().
- ONE model lock (`MODEL_LOCK`) is taken per Cactus call, never per job.
- Cactus calls cannot be interrupted from Python. shortcut: the "timeout" is a soft,
  measured one: a call that returns after MODEL_TIMEOUT_S is treated as failed and its
  result discarded. It does not stop a call that hangs. Upgrade: run Cactus in a
  subprocess that can be killed.
- Every step falls back; the file is still indexed (see build_card).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import extractors as ex
from .config import apply_env, get_settings

MODEL_LOCK = threading.Lock()   # shared with ai_classify: one model call at a time

NEEDLE_SCHEMA = {
    "name": "file_card",
    "description": "Describe a file: a short title, a one-sentence summary and a few keywords.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title of the document"},
            "summary": {"type": "string", "description": "One sentence summary"},
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Key topics"},
        },
        "required": ["title", "summary", "keywords"],
    },
}

_state: dict = {"needle": None, "mirage": None, "failed": {}, "loaded": set()}


class ModelTimeout(Exception):
    pass


ELLIPSIS = "\u2026"


def one_line(s: str, limit: int) -> str:
    """First line of `s`, at most `limit` characters, ending in an ellipsis when cut."""
    lines = (s or "").strip().splitlines() or [""]
    first = lines[0].strip()
    if len(first) > limit:
        return first[: limit - 1].rstrip() + ELLIPSIS
    return first + (ELLIPSIS if len(lines) > 1 else "")


def clip_error(s: str, limit: int = 200) -> str:
    """One line, at most `limit` characters. The provenance suffix is kept: only the front is cut."""
    s = " ".join((s or "").split())
    if len(s) <= limit:
        return s
    head, sep, tail = s.rpartition(" | ")
    if sep and len(tail) < limit - 20:
        return head[: limit - len(tail) - len(sep) - 1].rstrip() + ELLIPSIS + sep + tail
    return s[: limit - 1] + ELLIPSIS


def _load_error(stack: str) -> Exception | None:
    return _state["failed"].get(stack)


def _get(stack: str):
    """Load a Cactus stack once. A load failure is cached (no retry per file)."""
    if stack in _state["failed"]:
        raise RuntimeError(f"{stack} unavailable: {_state['failed'][stack]}")
    if _state.get(stack) is not None:
        return _state[stack]
    apply_env()
    try:
        import cactus
        if stack == "needle":
            obj = cactus.Cactus(tools=[NEEDLE_SCHEMA], auto_date=False, stateless=True)
        elif stack == "mirage":
            obj = cactus.Mirage()
        else:
            raise ValueError(stack)
    except Exception as exc:
        _state["failed"][stack] = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(f"{stack} failed to load: {exc}") from exc
    _state[stack] = obj
    _state["loaded"].add(stack)
    return obj


def _timed(fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    if dt > get_settings().model_timeout_s:
        raise ModelTimeout(f"model call took {dt:.0f}s (soft limit {get_settings().model_timeout_s:.0f}s)")
    return out


def loaded_flags() -> dict:
    return {"cactus": bool(_state["loaded"]),
            "failed": dict(_state["failed"])}


def close() -> None:
    """Close the held Needle agent (called on app shutdown)."""
    with MODEL_LOCK:
        n = _state.get("needle")
        if n is not None:
            try:
                n.close()
            except Exception:
                pass
        _state["needle"] = None
        _state["mirage"] = None
        _state["loaded"].clear()


# ---- model calls (each takes the model lock) ------------------------------------

def structured(text: str) -> dict | None:
    """Needle 3: {title, summary, keywords} or None when the model gives nothing valid."""
    with MODEL_LOCK:
        agent = _get("needle")
        res = _timed(lambda: agent.complete(text[:1500], max_new_tokens=160))
    calls = (res or {}).get("function_calls") or (res or {}).get("suppressed_calls") or []
    if not calls:
        return None
    args = calls[0].get("arguments") if isinstance(calls[0], dict) else None
    if not isinstance(args, dict):
        return None
    kw = args.get("keywords")
    return {
        "title": args.get("title") if isinstance(args.get("title"), str) else "",
        "summary": args.get("summary") if isinstance(args.get("summary"), str) else "",
        "keywords": [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else [],
    }


def describe_image(path: Path) -> str:
    """Mirage: OCR lines + scene.style + region names. Reasoning fragments are dropped
    when they say the text could not be read."""
    with MODEL_LOCK:
        mirage = _get("mirage")
        out = _timed(lambda: mirage.describe(str(path)))
    parts: list[str] = []
    style = ((out or {}).get("scene") or {}).get("style")
    if style:
        parts.append(f"{style} image")
    regions = [r.get("name") for r in (out or {}).get("regions") or [] if isinstance(r, dict) and r.get("name")]
    if regions:
        parts.append("regions: " + ", ".join(dict.fromkeys(regions)))
    lines = [t.get("string", "").strip() for t in (out or {}).get("text") or [] if isinstance(t, dict)]
    lines = [l for l in lines if l]
    reasoning = (out or {}).get("reasoning") or ""
    frags = [f.strip() for f in reasoning.split("|") if f.strip()]
    frags = [f for f in frags if not f.lower().startswith("lang:")
             and "cannot read" not in f.lower() and "unclear" not in f.lower()]
    text = ". ".join(parts)
    if frags:
        text += (". " if text else "") + frags[0]
    if lines:
        text += ("\n" if text else "") + "\n".join(lines)
    return text.strip()


def transcribe_audio(path: Path) -> str:
    """Whistle via cactus.transcribe(path, language=None). Non-16 kHz needs soxr."""
    with MODEL_LOCK:
        apply_env()
        if "whistle" in _state["failed"]:
            raise RuntimeError(f"whistle unavailable: {_state['failed']['whistle']}")
        try:
            import cactus
            res = _timed(lambda: cactus.transcribe(str(path), language=None))
            _state["loaded"].add("whistle")
        except ModelTimeout:
            raise
        except Exception as exc:
            if "whistle" not in _state["loaded"]:  # never worked: cache the failure (no retry per file)
                _state["failed"]["whistle"] = f"{type(exc).__name__}: {exc}"
            raise
    return ((res or {}).get("text") or "").strip()


# ---- the per-file card ------------------------------------------------------------

def build_card(path: Path, kind: str, name: str) -> dict:
    """Extract content, call Cactus where useful, merge per field with fallbacks.

    Returns dict(title, summary, keywords, text_excerpt, ai_status, ai_error).
    ai_status: ok | fallback | error (table in docs/review/phase-1.md).
    """
    cfg = get_settings()
    notes: list[str] = []          # errors / reasons
    prov = {"title": "fallback", "summary": "fallback", "keywords": "fallback"}
    text = ""
    source_model = None            # which model produced `text` (mirage / whistle)
    meta_line = ""
    status_error = False

    # 1. get raw text, read-only
    try:
        if kind == "text":
            text = ex.read_text(path)
        elif kind == "pdf":
            try:
                text = ex.read_pdf(path, cfg.pdf_max_pages)
            except ex.SoftFail as exc:
                notes.append(str(exc))
                meta_line = "PDF document"
        elif kind == "image":
            meta_line = ex.image_meta(path)
            try:
                text = describe_image(path)
                source_model = "mirage"
                if not text:
                    notes.append("image model returned nothing")
            except Exception as exc:
                notes.append(f"image model: {type(exc).__name__}: {exc}")
        elif kind == "audio":
            meta_line = ex.wav_meta(path)
            try:
                text = transcribe_audio(path)
                source_model = "whistle"
                if not text:
                    notes.append("no speech recognised")
            except Exception as exc:
                notes.append(f"audio model: {type(exc).__name__}: {exc}")
    except ex.ExtractError as exc:
        status_error = True
        notes.append(str(exc))
        meta_line = meta_line or f"{kind} file"

    text = text.strip()

    # 2. Needle on the text (best effort)
    ai = None
    if len(text) >= 20 and not status_error:
        try:
            ai = structured(text)
            if ai is None:
                notes.append("needle empty")
        except Exception as exc:
            notes.append(f"needle: {type(exc).__name__}: {exc}")

    # 3. per-field merge
    title = ""
    # Needle copies spans from the Mirage description ("Bar"), so images keep the filename title.
    if ai and kind != "image" and 3 <= len(ai["title"].strip()) <= 80:
        if ex.is_grounded(ai["title"], text):
            title, prov["title"] = ai["title"].strip(), "model"
        else:
            prov["title"] = "fallback(ungrounded)"
    if not title:
        title = ex.title_from_name(name)

    summary = ""
    if ai and len(ai["summary"].strip()) >= 20:
        if ex.is_grounded(ai["summary"], text):
            summary, prov["summary"] = ex.cut_text(ai["summary"].strip(), 300), "model"
        else:
            prov["summary"] = "fallback(ungrounded)"
    ungrounded = prov["summary"] == "fallback(ungrounded)"  # the model summary was rejected
    if not summary and text and source_model == "mirage":  # keep the OCR lines: they make it searchable
        summary, prov["summary"] = ex.cut_text(" | ".join(text.splitlines()), 300), source_model
    elif not summary and text and source_model:
        summary, prov["summary"] = ex.fallback_summary(text), source_model
    if not summary and text:
        summary = ex.fallback_summary(text)
    if not summary:
        summary = meta_line or f"{kind} file"
    if ungrounded:
        prov["summary"] = "fallback(ungrounded)"  # keep the marker even when OCR or speech text fills in
    if meta_line and kind in ("image", "audio") and prov["summary"].startswith("fallback"):
        summary = f"{meta_line}. {summary}" if summary != meta_line else summary

    kws, kw_src = ex.clean_keywords(ai["keywords"] if ai else None, text or title)
    prov["keywords"] = kw_src

    if status_error:
        status = "error"
    elif prov["title"] == "model" or prov["summary"] in ("model", "mirage", "whistle"):
        status = "ok" if not any(n.startswith(("needle:", "image model:", "audio model:")) for n in notes) else "fallback"
    else:
        status = "fallback"

    note = "title:%s,summary:%s,keywords:%s" % (prov["title"], prov["summary"], prov["keywords"])
    if status == "ok":  # ok means no error text: side notes go into the provenance (L5)
        ai_error = clip_error(note + "".join(",note:" + one_line(n, 60) for n in notes), 200)
    elif notes:
        ai_error = clip_error("; ".join(one_line(n, 80) for n in notes) + " | " + note, 200)
    else:
        ai_error = note
    return {
        "title": title, "summary": summary, "keywords": kws,
        "text_excerpt": (text or meta_line)[: cfg.excerpt_chars],
        "ai_status": status,
        "ai_error": ai_error,
    }
