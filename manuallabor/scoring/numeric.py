"""has_numeric_spec: a rule, not a score (design 3). Numeric-spec blocks are always queued."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.text import MODEL_RE

NUM: Final = r"[±∓+\-−]?(?:\d+(?:[.,]\d+)*(?:[ -]\d+/\d+)?|\d+/\d+)"

# Unit lexicon (abbreviations and plurals). Alternatives are longest-first inside each group;
# every unit must be followed by a non-letter (checked by the quantity pattern).
_TORQUE: Final = (
    r"N\s?[·.\-]?\s?m|Nm|kN[·.\-]?m|ft\.?\s?[·.\-]?\s?[l1I]bf?s?\.?|lbf?s?\.?\s?[·.\-]?\s?ft\.?"
    r"|in\.?\s?[·.\-]?\s?lbf?s?\.?|kgf?[·.\-]?[cm]?m"
)
_PRESSURE: Final = r"[Pp]\.\s?[Ss]\.\s?[Ii]\.?|psig?|PSIG?|kPa|MPa|Pa|mbar|bar|in\.?\s?Hg|mm\s?Hg"
_ELECTRIC: Final = (
    r"V\s?(?:DC|AC|dc|ac)|volts?|Volts?|kV|mV|amperes?|amps?|mA|kVA|VA|kW|watts?|Watts?"
    r"|ohms?|Ohms?|k[ΩΩ]|M[ΩΩ]|[ΩΩ]|kHz|MHz|Hz|V|A|W"
)
_VOLUME: Final = (
    r"gallons?|gals?\.?|quarts?|qts?\.?|pints?|liters?|litres?|mL|ml|cc"
    r"|cu\.?\s?in\.?|cu\.?\s?ft\.?|cubic\s+(?:inch(?:es)?|feet|foot)|L"
)
_LENGTH: Final = r"inches|inch|in\.?|feet|foot|ft\.?|mm|cm|km|[µμu]m|m|\"|″|'|′"
_MASS: Final = r"pounds?|lbs?\.?|tons?|kg|mg|oz|g"
_TEMP: Final = r"°\s?[CF]|degrees?(?:\s?[CF](?![A-Za-z]))?|deg\.?|°"
_RATE: Final = r"rpm|RPM|r/min|blows?\s+per\s+min(?:ute)?\.?|bpm|BPM|mph|m/s"
_TIME: Final = r"hours?|hrs?\.?|minutes?|min\.?|seconds?|secs?\.?|ms|h|s"
_OTHER: Final = r"%|dBA?|K"
UNIT: Final = (
    rf"(?:{_TORQUE}|{_RATE}|{_PRESSURE}|{_VOLUME}|{_ELECTRIC}|{_TEMP}|{_MASS}|{_TIME}"
    rf"|{_LENGTH}|{_OTHER})"
)

# Single-letter units that read as OCR garbage or plurals when glued to a number (5s, 1V,
# 1970s): glued, they need a number of >= 2 digits or a decimal; s and h need a space.
_WEAK_GLUED: Final = frozenset({"V", "A", "W", "L", "m", "g", "K"})
_SPACE_ONLY: Final = frozenset({"s", "h"})
_GLUED_ONLY: Final = frozenset({'"', "″", "'", "′"})
_DIMENSION_WORD_RE: Final = re.compile(
    r"(?i)\b(?:dia(?:meter|\.)?|bore|stroke|depth|width|height|length|long|wide|deep|high"
    r"|thick(?:ness)?|radius|size|gap|clearance|travel|reach|span|opening|O\.?D|I\.?D)\b"
)
_SECTION_CONTEXT_RE: Final = re.compile(
    r"(?i)\b(?:section|chapter|part|appendix|annex|volume|vol\.)\s*$"
)
_CODE_GARBAGE_RE: Final = re.compile(r"\d{1,3}[A-Z]")  # OCR garbage: 50S, 0G, 1V, 2B
_APPENDIX_REF_RE: Final = re.compile(r"[A-Z]-\d{1,3}")  # appendix page refs: A-1, B-12

QUANTITY_RE: Final = re.compile(
    rf"(?<![\w.]){NUM}(?:\s?(?:-|–|to|\.\.)\s?{NUM})?(?P<sp>\s?)(?P<unit>{UNIT})(?![A-Za-z])"
)
PART_NUMBER_RE: Final = re.compile(
    r"(?i:\b(?:P/?N|part\s*(?:no\.?|number|#)|ref\.?|cat\.?\s*no\.?|sku|order\s*no\.?|FSN|NSN"
    r"|NIIN|s/n|model(?:\s*(?:no\.?|number))?|serial\s*(?:no\.?|numbers?|#)?))(?![A-Za-z])"
    r"\s*[:#]?\s*(?P<value>(?=[A-Z0-9./-]*\d)[A-Z0-9][A-Z0-9./-]{2,})"
)

NUMERIC_SPEC_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("quantity", QUANTITY_RE),
    ("tolerance", re.compile(r"±\s?\d|\+\s?/\s?-\s?\d|\d\s?(?:±|\+/-)")),
    ("part_number", PART_NUMBER_RE),
    ("code", MODEL_RE),
    ("dimension", re.compile(r"\d+(?:[.,]\d+)?\s?[x×]\s?\d+(?:[.,]\d+)?")),
    (
        "spec_word",
        re.compile(
            r"(?i)\b(?:torque|voltage|current|pressure|tolerance|clearance|capacity|rating|gap"
            r"|preload)\b[^.\n]{0,40}?\d"
        ),
    ),
)


def _quantity_ok(m: re.Match[str], t: str) -> bool:
    """False positives of the quantity rule: ``3 in the list``, ``1970s``, ``5s``, ``1V``,
    a quoted number taken for inches."""
    unit, sp = m.group("unit"), m.group("sp")
    num = t[m.start() : m.start("sp")]
    digits = sum(c.isdigit() for c in num)
    decimal = any(c in ".,/" for c in num.strip())
    if unit in _SPACE_ONLY and not sp:
        return False
    if unit in _WEAK_GLUED and not sp and digits < 2 and not decimal:
        return False
    if unit in _GLUED_ONLY:
        before = t[m.start() - 1] if m.start() > 0 else ""
        return not sp and before not in "\"'“”‘’″′"
    if unit in ("in", "in."):
        nxt = t[m.end() : m.end() + 1]
        if unit == "in" and nxt and nxt not in ",;:)]":
            return False  # `3 in the list`, `2 in each hand`
        before = t[max(0, m.start() - 40) : m.start()].split("\n")[-1]
        return decimal or _DIMENSION_WORD_RE.search(before) is not None
    return True


def _code_ok(m: re.Match[str], t: str, model_tokens: frozenset[str]) -> bool:
    s = m.group(0)
    if s in model_tokens or _CODE_GARBAGE_RE.fullmatch(s) or _APPENDIX_REF_RE.fullmatch(s):
        return False
    return _SECTION_CONTEXT_RE.search(t[max(0, m.start() - 20) : m.start()]) is None


FAITH_NUM_RE: Final = re.compile(r"(?<!\w)[±∓+\u2212-]?\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*")
MAX_DETAIL_SPECS: Final = 5


def find_numeric_specs(text: str, product_model: str | None) -> list[str]:
    """Spec matches in text order (ties by rule order), de-duplicated, stripped."""
    t = unicodedata.normalize("NFKC", text)
    model_tokens = frozenset(product_model.split()) if product_model else frozenset()
    hits: list[tuple[int, int, str]] = []
    for ri, (name, rx) in enumerate(NUMERIC_SPEC_RULES):
        for m in rx.finditer(t):
            s = m.group(0).strip()
            if not s:
                continue
            if name == "quantity" and not _quantity_ok(m, t):
                continue
            if name == "code" and not _code_ok(m, t, model_tokens):
                continue
            if name == "part_number" and m.group("value") in model_tokens:
                continue
            hits.append((m.start(), ri, s))
    hits.sort()
    return list(dict.fromkeys(s for _, _, s in hits))


def numeric_specs_for(block: Block, product_model: str | None) -> tuple[bool, list[str]]:
    """(has_numeric_spec, specs: from raw_text first, then the other readers)."""
    if block.type in (BlockType.header, BlockType.footer, BlockType.figure):
        return False, []
    specs = find_numeric_specs(block.raw_text, product_model)
    for k in sorted(block.raw_text_by_parser):
        for s in find_numeric_specs(block.raw_text_by_parser[k], product_model):
            if s not in specs:
                specs.append(s)
    if block.type == BlockType.table and block.table is not None:
        cells = [c.text.strip() for c in block.table.cells if not c.is_header]
        numeric_cells = [c for c in cells if any(ch.isdigit() for ch in c)]
        if not numeric_cells:
            return False, []
        for c in numeric_cells:
            if c not in specs:
                specs.append(c)
        return True, specs
    return bool(specs), specs


def has_numeric_spec(block: Block, product_model: str | None) -> bool:
    return numeric_specs_for(block, product_model)[0]
