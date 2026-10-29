"""Shared text helpers and regexes."""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[^\s|•]+")
NUMERIC_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*")
SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
CAPTION_RE = re.compile(r"^(?:Figure|Fig\.|Table)\s+\d+[A-Za-z]?(?:[.:]|\s)")
BULLETS = "•·◦▪‣*–-●¢+"  # incl. OCR mis-reads of a bullet: ¢ (Tesseract), + (RapidOCR)
_BULLET_RE = re.compile(r"^(?:[•·◦▪‣●¢*–\-+]|o)\s")  # "o " is OCR of ◦


def starts_with_bullet(text: str) -> bool:
    """A line opens with a bullet glyph (or a common OCR reading of one) and a space."""
    return _BULLET_RE.match(text.lstrip()) is not None


MODEL_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]{1,15}\b")

_DIGITS_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def numeric_tokens(text: str) -> list[str]:
    return NUMERIC_TOKEN_RE.findall(text)


def hf_key(text: str) -> str:
    """Header/footer grouping key: casefold, digit runs -> '#', whitespace collapsed."""
    return _WS_RE.sub(" ", _DIGITS_RE.sub("#", text.casefold())).strip()


def collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text)
