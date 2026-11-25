"""Read-only content extraction plus the non-AI fallbacks (title, summary, keywords).

Every file is opened with open(path, "rb") or a read-only library call. No models here,
so this module is safe to import and test without onnxruntime or cactus.
"""
from __future__ import annotations

import codecs
import re
import wave
from collections import Counter
from pathlib import Path

TEXT_READ_BYTES = 2 * 1024 * 1024  # decode at most the first 2 MB of a text file


class ExtractError(Exception):
    """The file could not be read or parsed (ai_status = error)."""


class SoftFail(Exception):
    """Readable file, but no usable text (ai_status = fallback). Message goes to ai_error."""


# ---- readers ------------------------------------------------------------------

def decode_text(raw: bytes) -> str:
    if raw.startswith(codecs.BOM_UTF8):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def read_text(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(TEXT_READ_BYTES)
    except OSError as exc:
        raise ExtractError(f"cannot read file: {exc}") from exc
    return decode_text(raw)


def read_pdf(path: Path, max_pages: int) -> str:
    from pypdf import PdfReader
    try:
        with open(path, "rb") as fh:
            reader = PdfReader(fh)
            if reader.is_encrypted:
                raise SoftFail("PDF is encrypted")
            parts: list[str] = []
            for page in reader.pages[:max_pages]:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) > 20000:
                    break
    except SoftFail:
        raise
    except OSError as exc:
        raise ExtractError(f"cannot read file: {exc}") from exc
    except Exception as exc:  # pypdf raises many types on broken files
        raise ExtractError(f"cannot parse PDF: {type(exc).__name__}: {exc}") from exc
    text = "\n".join(parts).strip()
    if not text:
        raise SoftFail("PDF has no extractable text (scanned?)")
    return text


def read_bytes(path: Path, limit: int) -> bytes:
    """The whole file, read-only, at most `limit` bytes (the scanner already skips bigger files)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(limit)
    except OSError as exc:
        raise ExtractError(f"cannot read file: {exc}") from exc


def render_pdf_pages(data: bytes, pages: int = 3, dpi: int = 200, max_pixels: int = 12_000_000) -> list:
    """Render the first `pages` pages of a PDF given as bytes to BGR uint8 arrays, in memory only.
    The scale is lowered per page so width x height stays under `max_pixels` (an A0 page at
    200 dpi would be about 100 Mpx). pypdfium2 is imported lazily; nothing is written to disk."""
    import io

    import numpy as np
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    out = []
    try:
        for i in range(min(pages, len(pdf))):
            page = pdf[i]
            w, h = page.get_size()                      # PDF points (1/72 inch)
            scale = dpi / 72
            if w * h * scale * scale > max_pixels:
                scale = (max_pixels / (w * h)) ** 0.5
            img = page.render(scale=scale).to_pil().convert("RGB")
            out.append(np.asarray(img)[:, :, ::-1].copy())  # RGB -> BGR for rapidocr
            page.close()
    finally:
        pdf.close()
    return out


def image_meta(path: Path) -> str:
    """Basic metadata line for an image (also verifies it opens)."""
    from PIL import Image
    try:
        with open(path, "rb") as fh:
            with Image.open(fh) as im:
                return f"{im.format or 'Image'} image, {im.width}x{im.height} pixels"
    except OSError as exc:  # includes UnidentifiedImageError
        raise ExtractError(f"cannot read image: {exc}") from exc
    except Exception as exc:  # DecompressionBombError etc.
        raise ExtractError(f"cannot read image: {type(exc).__name__}: {exc}") from exc


def wav_meta(path: Path) -> str:
    """Summary from the WAV header: duration, rate, channels. Never raises."""
    try:
        with open(path, "rb") as fh:
            with wave.open(fh, "rb") as w:
                rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
                dur = n / rate if rate else 0
                return f"WAV audio, {dur:.1f} s, {rate} Hz, {'mono' if ch == 1 else str(ch) + ' channels'}"
    except Exception:
        try:
            return f"WAV audio file, {Path(path).stat().st_size // 1024} KB"
        except OSError:
            return "WAV audio file"


# ---- fallbacks ------------------------------------------------------------------

STOPWORDS = set("""a about above after again all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have
having he her here hers him his how i if in into is it its just me more most my no nor not now of off on
once only or other our out over own same she should so some such than that the their them then there these
they this those through to too under until up us very was we were what when where which while who whom why
will with would you your yours dear please thanks regards hello""".split())

_EMAILISH = re.compile(r"\S+@\S+|\+?\d[\d\-\s().]{6,}\d|https?://\S+|www\.\S+", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
_ONLY_NUM_DATE = re.compile(r"^[\d\s\-/.,:;$\u20ac\u00a3%#()]+$")
_SENT = re.compile(r"(?<=[.!?])\s+")


def cut_text(s: str, limit: int) -> str:
    """At most `limit` characters; a cut text ends in an ellipsis (C-2)."""
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "\u2026"


def title_from_name(name: str) -> str:
    stem = Path(name).stem
    t = re.sub(r"[_\-.]+", " ", stem).strip() or stem or name
    return (t[0].upper() + t[1:])[:80]


def _meaningful_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 20:
            continue
        if line.startswith("#") or _ONLY_NUM_DATE.match(line):
            continue
        if line.endswith(":") and len(line) < 60:
            continue
        out.append(re.sub(r"^[\-*>\s]+", "", line))
    return [l for l in out if len(l) >= 20]


def fallback_summary(text: str, limit: int = 300) -> str:
    """First one or two meaningful sentences, at most ~limit chars."""
    lines = _meaningful_lines(text)
    if not lines:
        return re.sub(r"\s+", " ", text).strip()[:limit]
    sents: list[str] = []
    for line in lines:
        for s in _SENT.split(line):
            s = s.strip()
            if len(s) >= 12:
                sents.append(s)
            if len(sents) >= 2:
                break
        if len(sents) >= 2:
            break
    if not sents:
        sents = [lines[0]]
    out = " ".join(sents[:2])
    if len(out) > limit:
        out = cut_text(out, limit)
    return out


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"\w+", s.lower(), re.UNICODE) if len(w) > 2]


def is_grounded(candidate: str, source: str, min_share: float = 0.9) -> bool:
    """True when at least `min_share` of the candidate's word tokens (lowercase, length > 2)
    occur in the source text. Guards against model output with invented words."""
    toks = _tokens(candidate)
    if not toks:
        return False
    have = set(_tokens(source))
    return sum(1 for w in toks if w in have) / len(toks) >= min_share


def _bad_keyword(k: str) -> bool:
    return (not k or _EMAILISH.search(k) is not None or k.lower() in STOPWORDS
            or not re.search(r"[A-Za-z]", k) or len(k) < 3)


def frequency_keywords(text: str, n: int = 6, exclude: set[str] | None = None) -> list[str]:
    clean = _EMAILISH.sub(" ", text)
    words = [w.strip("'-").lower() for w in _WORD.findall(clean)]
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) >= 3)
    exclude = exclude or set()
    return [w for w, _ in counts.most_common(n * 3) if w not in exclude][:n]


def clean_keywords(ai_keywords: list | None, text: str, limit: int = 6) -> tuple[list[str], str]:
    """Keep grounded model keywords (<=4 words, <=30 chars), top up by frequency.
    Returns (keywords, source): model | model+freq | freq | none."""
    out: list[str] = []
    seen: set[str] = set()
    ai_used = False

    def add(k: str, from_ai: bool) -> None:
        nonlocal ai_used
        k = k.strip(" .,;:!?\"'()[]{}").strip()
        if _bad_keyword(k) or k.lower() in seen or len(out) >= limit:
            return
        seen.add(k.lower())
        out.append(k)
        ai_used = ai_used or from_ai

    for span in ai_keywords or []:
        if not isinstance(span, str):
            continue
        for part in re.split(r"[,;\n]", span):
            part = part.strip(" .,;:!?\"'()[]{}").strip()
            # Same 90% grounding rule as the title/summary; long spans are dropped, not split.
            if (part and len(part.split()) <= 4 and len(part) <= 30
                    and is_grounded(part, text)):
                add(part, True)
    n_ai = len(out)
    for w in frequency_keywords(text, limit, exclude=seen):
        add(w, False)
    source = "none" if not out else ("model" if ai_used and len(out) == n_ai else
                                     "model+freq" if ai_used else "freq")
    return out, source
