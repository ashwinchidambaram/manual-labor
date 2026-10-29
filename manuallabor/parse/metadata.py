"""Title and product-model inference (design 01-parse section 8.3)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuallabor.contracts.enums import Task
from manuallabor.contracts.llm import Message
from manuallabor.parse.classify import body_size_of
from manuallabor.parse.text import MODEL_RE, SECTION_RE, collapse_ws
from manuallabor.parse.types import Line
from manuallabor.providers.base import Provider, ProviderError

TITLE_PAGE_MAX_WORDS = 60
TITLE_SIZE_FACTOR = 1.4
MAX_LLM_CHARS = 2000

_MODEL_AFTER_WORD = re.compile(r"\bModel\s+(" + MODEL_RE.pattern + ")")
_EXT_LIKE = re.compile(r"\.\w{2,4}\b")

LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": ["string", "null"]},
        "product_model": {"type": ["string", "null"]},
    },
    "required": ["title", "product_model"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Metadata:
    title: str | None = None
    product_model: str | None = None
    product_model_inferred: bool = False
    title_inferred: bool = False


TITLE_LEN = (3, 200)
TITLE_MAX_WORDS = 30
MODEL_LEN = (2, 60)
MODEL_MAX_WORDS = 6
# An LLM-supplied model name: starts alphanumeric; letters, digits, space, '-', '.', '/' after.
MODEL_SHAPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./-]*$")
_GENERIC_STEM_PART = re.compile(
    r"^(?:manual|guide|service|rev|revision|user|owner|operator|handbook|man|doc|docs|"
    r"v\d+|rev\d+|r\d+|\d{4}|final|draft|copy)$",
    re.IGNORECASE,
)


def _printable_one_line(val: str) -> bool:
    return val.isprintable()  # False for newlines, tabs and control characters


def valid_title(val: str) -> bool:
    return (
        TITLE_LEN[0] <= len(val) <= TITLE_LEN[1]
        and len(val.split()) <= TITLE_MAX_WORDS
        and _printable_one_line(val)
    )


def valid_model(val: str) -> bool:
    return (
        MODEL_LEN[0] <= len(val) <= MODEL_LEN[1]
        and len(val.split()) <= MODEL_MAX_WORDS
        and _printable_one_line(val)
        and MODEL_SHAPE_RE.match(val) is not None
    )


def _whole_sequence_in(val: str, haystack: str) -> bool:
    """`val` occurs in `haystack` as whole words (case-insensitive, whitespace-collapsed)."""
    pat = r"(?<![A-Za-z0-9])" + re.escape(_norm(val)).replace(r"\ ", r"\s+") + r"(?![A-Za-z0-9])"
    return re.search(pat, _norm(haystack)) is not None


def title_from_lines(lines: Sequence[Line], body: float | None) -> str | None:
    """Title-page heuristic: the largest lines on a short first page."""
    if body is None or not lines:
        return None
    words = sum(len(ln.text.split()) for ln in lines)
    if words > TITLE_PAGE_MAX_WORDS:
        return None
    sized = [ln for ln in lines if ln.size is not None and not SECTION_RE.match(ln.text.strip())]
    if not sized:
        return None
    top = max(ln.size for ln in sized if ln.size is not None)
    if top < TITLE_SIZE_FACTOR * body:
        return None
    chosen = [ln for ln in sized if ln.size is not None and ln.size >= top - 0.5]
    chosen.sort(key=lambda ln: (round(ln.bbox[1], 1), round(ln.bbox[0], 1)))
    return collapse_ws(" ".join(ln.text for ln in chosen)) or None


def accept_embedded_title(title: str | None) -> str | None:
    if not title:
        return None
    t = collapse_ws(title)
    if len(t.split()) < 2 or _EXT_LIKE.search(t) or t.startswith("Microsoft Word"):
        return None
    return t


def _from_title(title: str, token: str) -> str:
    words = title.split()
    for i, w in enumerate(words):
        if token in w:
            return " ".join(words[: i + 1])
    return token


def find_product_model(page1_text: str, title: str | None, filename: str) -> str | None:
    m = _MODEL_AFTER_WORD.search(page1_text)
    if m:
        token = m.group(1)
        if title and token in title:
            return _from_title(title, token)
        return token
    if title:
        m2 = MODEL_RE.search(title)
        if m2:
            return _from_title(title, m2.group(0))
    return _model_from_stem(Path(filename).stem)


def _model_from_stem(stem: str) -> str | None:
    """A filename-stem token that looks like a model once generic words and years are removed."""
    for tok in re.split(r"[\s_.]+", stem.upper()):
        parts = [p for p in tok.split("-") if p and not _GENERIC_STEM_PART.match(p)]
        cand = "-".join(parts)
        if cand and MODEL_RE.fullmatch(cand):
            return cand
    return None


def _norm(s: str) -> str:
    return collapse_ws(s).casefold()


def llm_infer(
    provider: Provider,
    page1_text: str,
    filename: str,
    warn: Callable[[str], None],
    want_title: bool = True,
    want_model: bool = True,
) -> tuple[str | None, str | None]:
    """Ask the metadata model; accept a value only if it appears verbatim in the evidence."""
    stem = Path(filename).stem
    evidence = page1_text + "\n" + stem + "\n" + re.sub(r"[-_.]+", " ", stem)
    messages = [
        Message(
            role="system",
            content=(
                "Extract the document title and the product model name from the text. "
                "Copy them exactly as written; answer null when absent. Reply with JSON."
            ),
        ),
        Message(
            role="user",
            content=f"Filename: {filename}\n\nPage 1 text:\n{page1_text[:MAX_LLM_CHARS]}",
        ),
    ]
    try:
        res = provider.chat(Task.metadata, messages, json_schema=LLM_SCHEMA)
    except ProviderError as exc:
        warn(f"metadata LLM unavailable: {exc}")
        return None, None
    data = res.parsed if isinstance(res.parsed, dict) else {}
    out: dict[str, str | None] = {"title": None, "product_model": None}
    for key, wanted in (("title", want_title), ("product_model", want_model)):
        val = data.get(key)
        if not wanted or not isinstance(val, str) or not val.strip():
            continue
        shown = val[:60]
        ok = valid_title(val) if key == "title" else valid_model(val)
        if not ok:
            warn(f"metadata LLM {key} {shown!r} rejected: not a plausible {key}")
        elif not _whole_sequence_in(val, evidence):
            warn(f"metadata LLM {key} {shown!r} rejected: not found in the document text")
        else:
            out[key] = collapse_ws(val)
    return out["title"], out["product_model"]


def infer_metadata(
    *,
    page1_lines: Sequence[Line],
    body: float | None,
    embedded_title: str | None,
    filename: str,
    provider: Provider | None,
    warn: Callable[[str], None],
    page1_text: str | None = None,
) -> Metadata:
    text = page1_text if page1_text is not None else "\n".join(ln.text for ln in page1_lines)
    title = title_from_lines(page1_lines, body) or accept_embedded_title(embedded_title)
    model = find_product_model(text, title, filename)
    inferred = False
    title_inferred = False
    if (title is None or model is None) and provider is not None:
        t, m = llm_infer(
            provider, text, filename, warn, want_title=title is None, want_model=model is None
        )
        if title is None and t is not None:
            title, title_inferred = t, True
        if model is None and m is not None:
            model, inferred = m, True
    return Metadata(
        title=title,
        product_model=model,
        product_model_inferred=inferred,
        title_inferred=title_inferred,
    )


def page1_lines_pdf(
    path: Path, max_pages_for_body: int = 20
) -> tuple[list[Line], float | None, str | None]:
    """Cheap PyMuPDF pass for ingest: page-1 lines, body size estimate, embedded title."""
    from manuallabor.parse.pdf_pymupdf import open_pdf

    with open_pdf(path) as doc:
        embedded = (doc.metadata or {}).get("title")
        all_lines: list[Line] = []
        page1: list[Line] = []
        for i in range(min(doc.page_count, max_pages_for_body)):
            d = doc[i].get_text("dict")
            for bi, blk in enumerate(d["blocks"]):
                if blk.get("type") != 0:
                    continue
                for li, ln in enumerate(blk["lines"]):
                    spans = [s for s in ln["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    best = max(spans, key=lambda s: len(s["text"].strip()))
                    line = Line(
                        text="".join(s["text"] for s in ln["spans"]).rstrip(),
                        bbox=[round(float(v), 3) for v in ln["bbox"]],
                        size=round(float(best["size"]), 3),
                        native_id=f"b{bi}.l{li}",
                    )
                    all_lines.append(line)
                    if i == 0:
                        page1.append(line)
    return page1, body_size_of(all_lines), embedded
