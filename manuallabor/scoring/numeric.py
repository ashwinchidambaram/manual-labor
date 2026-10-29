"""has_numeric_spec: a rule, not a score (design 3). Numeric-spec blocks are always queued."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from manuallabor.contracts.block import Block
from manuallabor.contracts.enums import BlockType
from manuallabor.parse.text import MODEL_RE

NUM: Final = r"[±∓+\-−]?\d+(?:[.,]\d+)*"
UNIT: Final = (
    r"(?:N\s?[·.\-]?\s?m|Nm|kN|N|lbf?[·.\-\s]?ft|ft[·.\-\s]?lbf?s?|in[·.\-\s]?lbf?s?"
    r"|kgf?[·.\-]?[cm]?m|mm|cm|km|[µμu]m|m|in|ft|kg|g|mg|lbs?|oz|kPa|MPa|Pa|mbar|bar|psi"
    r"|V(?:DC|AC|dc|ac)?|mV|kV|mA|A|kVA|VA|kW|W|[ΩΩ]|k[ΩΩ]|M[ΩΩ]|ohms?|kHz|MHz|Hz|rpm|RPM"
    r"|°\s?[CF]|°|K|mL|ml|L|cc|gal|qt|ms|sec|s|min|hrs?|hours?|h|minutes?|seconds?|%|dBA?)"
)

NUMERIC_SPEC_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "quantity",
        re.compile(rf"(?<![\w.]){NUM}(?:\s?(?:-|–|to|\.\.)\s?{NUM})?\s?{UNIT}(?![A-Za-z])"),
    ),
    ("tolerance", re.compile(r"±\s?\d|\+\s?/\s?-\s?\d|\d\s?(?:±|\+/-)")),
    (
        "part_number",
        re.compile(
            r"(?i:\b(?:P/?N|part\s*(?:no\.?|number|#)|ref\.?|cat\.?\s*no\.?|sku|order\s*no\.?))"
            r"\s*[:#]?\s*[A-Z0-9][A-Z0-9./-]{2,}"
        ),
    ),
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
            if not s or (name == "code" and s in model_tokens):
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
