"""Figure descriptions (generated alt text) and tags (design 6). The reply is schema-validated
by the provider and post-validated here; it never touches ``caption_original``."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Final

from manuallabor.cleanup.types import DESC_MAX, DESCRIBE_PROMPT_VERSION, TAGS_MAX, DescribeOutcome
from manuallabor.contracts.enums import Task
from manuallabor.parse.text import collapse_ws
from manuallabor.providers.base import Provider, ProviderError, ProviderOutputError

DESCRIBE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["description", "tags"],
    "properties": {
        "description": {"type": "string", "minLength": 1, "maxLength": DESC_MAX},
        "tags": {
            "type": "array",
            "maxItems": TAGS_MAX,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^[a-z0-9][a-z0-9 /&+.-]{0,29}$"},
        },
    },
}
NOTE_MAX: Final = 200


def describe_prompt(caption: str | None, note: str | None = None) -> str:
    parts = [
        f"{DESCRIBE_PROMPT_VERSION}. Write alt text for this figure from a technical manual. "
        "Describe only what is visible (parts, layout, labels, arrows) in at most "
        f"{DESC_MAX} characters, and give up to {TAGS_MAX} short lowercase tags. Do not guess "
        "values, part numbers or measurements that are not legible, and do not copy the "
        'caption. Reply with JSON only: {"description": "...", "tags": ["..."]}.'
    ]
    if caption:
        parts.append(f"The figure's caption, for context only: {collapse_ws(caption)}")
    if note:
        parts.append(f"Your previous reply was rejected ({note}). Follow the format exactly.")
    return "\n".join(parts)


def validate_description(parsed: Any) -> str | None:
    """Post-validation after the schema: a non-empty description without control chars.
    Returns the reason it fails, or None."""
    if not isinstance(parsed, dict):
        return "reply is not an object"
    desc = parsed.get("description")
    if not isinstance(desc, str) or not collapse_ws(desc):
        return "empty description"
    if any(unicodedata.category(ch).startswith("C") for ch in collapse_ws(desc)):
        return "control characters in description"
    return None


@dataclass(frozen=True)
class Described:
    outcome: DescribeOutcome
    description: str | None
    tags: list[str]
    calls: int


def describe_figure(provider: Provider, png: bytes, caption: str | None) -> Described:
    """One call, one retry (with a rejection note, so a new input hash) on invalid output;
    ``invalid`` after that. A provider failure is ``error``. Never raises ProviderError."""
    note: str | None = None
    calls = 0
    for _ in range(2):
        calls += 1
        try:
            res = provider.vision(
                Task.vision, png, describe_prompt(caption, note), json_schema=DESCRIBE_SCHEMA
            )
        except ProviderOutputError as exc:
            note = str(exc)[:NOTE_MAX]
            continue
        except ProviderError:
            return Described("error", None, [], calls)
        err = validate_description(res.parsed)
        if err is not None:
            note = err
            continue
        assert isinstance(res.parsed, dict)
        tags = [str(t) for t in res.parsed.get("tags", [])]
        return Described("ok", collapse_ws(str(res.parsed["description"])), tags, calls)
    return Described("invalid", None, [], calls)
