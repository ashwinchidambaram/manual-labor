"""The only text transformations of an export (design 11 section 3.2-3.4). Pure."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from manuallabor.contracts._base import _fmt_utc
from manuallabor.contracts.article import ArticleFrontmatter

__all__ = [
    "FIGURE_LINE_RE",
    "alt_text",
    "figure_line",
    "heading_line",
    "render_list",
    "yaml_frontmatter",
    "yaml_scalar",
]

FRONTMATTER_KEYS: Final = (
    "id",
    "title",
    "source_doc",
    "source_file",
    "product_model",
    "pages",
    "sections",
    "figures",
    "blocks",
    "review",
    "generated_at",
)
FIGURE_LINE_RE: Final = re.compile(
    r"^!\[(?P<fid>FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}) — (?P<alt>.*)\]"
    r"\((?P<path>images/[a-z0-9-]+/FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}\.png)\)$"
)
_ENUM_LINE_RE: Final = re.compile(r"^(?:\(?\d{1,2}[.)]|[a-z][.)])\s")
_PLAIN_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9 _.,&()/'-]*$")
_RESERVED: Final = frozenset({"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"})
_WS_RE: Final = re.compile(r"\s+")


def heading_line(text: str, level: int) -> str:
    """A structure-node heading: H1 is the article title, so a top-level section is H2."""
    return "#" * min(6, 1 + level) + " " + text


def render_list(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        if line.startswith("• "):
            out.append("* " + line[2:])
        elif line == "" or line.startswith("* ") or _ENUM_LINE_RE.match(line):
            out.append(line)
        else:
            out.append("* " + line)
    return "\n".join(out)


def alt_text(
    figure_id: str, caption_original: str | None, description_generated: str | None
) -> str:
    """`<FIG-ID> — <caption>`: the original caption, else the generated description labelled
    as such (the label itself is literal), else `(no caption)`. `\\`, `[`, `]`, `)` and `<` of the
    caption or description are backslash-escaped (CommonMark punctuation escapes, so the rendered
    alt text is unchanged and no link parser ends the alt or the link early; `<` since review
    markers, so a caption can never read as one); whitespace is
    collapsed. Only alt text is escaped: article body text is never touched."""

    def esc(x: str) -> str:
        x = x.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        # `<` too (design 11 section 20): alt text never holds an HTML comment or a marker
        return x.replace(")", "\\)").replace("<", "\\<")

    cap = _WS_RE.sub(" ", caption_original or "").strip()
    if cap:
        return f"{figure_id} \u2014 {esc(cap)}"
    desc = _WS_RE.sub(" ", description_generated or "").strip()
    if desc:
        return f"{figure_id} \u2014 [generated] {esc(desc)}"
    return f"{figure_id} \u2014 (no caption)"


def figure_line(alt: str, image_path: str) -> str:
    return f"![{alt}]({image_path})"


def yaml_scalar(s: str, *, in_flow: bool = False) -> str:
    """Plain when safe, else a JSON string (a valid YAML double-quoted scalar)."""
    if (
        _PLAIN_RE.match(s)
        and not s.endswith(" ")
        and s.lower() not in _RESERVED
        and not (in_flow and "," in s)
    ):
        return s
    return json.dumps(s, ensure_ascii=False)


def _flow(items: Sequence[str | int]) -> str:
    if not items:
        return "[]"
    return (
        "["
        + ", ".join(str(i) if isinstance(i, int) else yaml_scalar(i, in_flow=True) for i in items)
        + "]"
    )


def _utc(dt: datetime) -> str:
    return str(_fmt_utc(dt))


def yaml_frontmatter(fm: ArticleFrontmatter) -> str:
    """The `---` block, keys in SPEC 6.2 order, hand-emitted so bytes never depend on PyYAML."""
    pm = "null" if fm.product_model is None else yaml_scalar(fm.product_model)
    r = fm.review
    rows = [
        ("id", yaml_scalar(fm.id)),
        ("title", yaml_scalar(fm.title)),
        ("source_doc", yaml_scalar(fm.source_doc)),
        ("source_file", yaml_scalar(fm.source_file)),
        ("product_model", pm),
        ("pages", _flow(fm.pages)),
        ("sections", _flow(fm.sections)),
        ("figures", _flow(fm.figures)),
        ("blocks", str(fm.blocks)),
        (
            "review",
            f"{{ approved: {r.approved}, edited: {r.edited}, overrides: {r.overrides} }}",
        ),
        ("generated_at", _utc(fm.generated_at)),
    ]
    assert tuple(k for k, _ in rows) == FRONTMATTER_KEYS
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in rows) + "---\n"
