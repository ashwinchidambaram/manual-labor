"""Validate an export zip by reading only the zip (design 11 section 5.3, SPEC 11.7)."""

from __future__ import annotations

import io
import json
import posixpath
import re
import zipfile
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from manuallabor import ids
from manuallabor.contracts.article import ArticleFrontmatter
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.manifest import Manifest
from manuallabor.export.render import FIGURE_LINE_RE
from manuallabor.export.types import Problem

__all__ = ["split_article", "validate_zip"]

KEYS: Final = [
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
]
_SLUG: Final = ids.SLUG_PATTERN
_ARTICLE_NAME: Final = re.compile(rf"^articles/{_SLUG}(?:--{_SLUG})?\.md$")
_IMAGE_NAME: Final = re.compile(
    rf"^images/(?P<slug>{_SLUG})/(?P<fid>FIG-[a-z0-9-]+-p\d{{3,4}}-\d{{2,3}})\.(?P<ext>png|svg|json)$"
)
SCHEMA_PATH: Final = Path(__file__).resolve().parents[2] / "schemas" / "Manifest.json"


class _Loader(yaml.SafeLoader):
    """SafeLoader without the timestamp resolver, so `generated_at` stays a string."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def split_article(text: str) -> tuple[dict[str, Any], str]:
    """(frontmatter mapping in file order, body starting at the blank line after `---`)."""
    if not text.startswith("---\n"):
        raise ValueError("article does not start with a frontmatter block")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise ValueError("frontmatter block is not closed")
    fm = yaml.load(text[4 : end + 1], Loader=_Loader)  # noqa: S506 (SafeLoader subclass)
    if not isinstance(fm, dict):
        raise ValueError("frontmatter is not a mapping")
    return fm, text[end + 5 :]


def _jsonschema_problems(data: Any, schema_path: Path | None) -> list[str]:
    import jsonschema

    p = schema_path or SCHEMA_PATH
    schema = (
        json.loads(p.read_text(encoding="utf-8")) if p.is_file() else Manifest.model_json_schema()
    )
    v = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in v.iter_errors(data)
    ][:5]


def _check_image(name: str, data: bytes) -> str | None:
    if name.endswith(".png"):
        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except Exception as exc:
            return f"PNG does not decode: {type(exc).__name__}: {exc}"
    elif name.endswith(".svg"):
        import xml.etree.ElementTree as ET  # noqa: N817

        try:
            ET.fromstring(data)  # noqa: S314 (a local file we wrote; no network entities)
        except ET.ParseError as exc:
            return f"SVG does not parse: {exc}"
    return None


def validate_zip(path: Path, *, schema_path: Path | None = None) -> list[Problem]:
    """Every problem found (empty = valid). Each carries the code of the check that caught it."""
    problems: list[Problem] = []

    def bad(code: str, where: str, detail: str) -> None:
        problems.append(Problem(code, where, detail))

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return [Problem("Z1", str(path), f"not a readable zip: {exc}")]
    with zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        # -- Z1 -----------------------------------------------------------------------------
        for n in sorted({n for n in names if names.count(n) > 1}):
            bad("Z1", n, "duplicate entry")
        for n in names:
            if n.startswith("/") or ".." in n.split("/") or n.endswith("/"):
                bad("Z1", n, "absolute, parent-relative or directory entry")
            elif not (
                n in ("README.md", "manifest.json")
                or _ARTICLE_NAME.match(n)
                or _IMAGE_NAME.match(n)
            ):
                bad("Z1", n, "unexpected entry")
        if names != sorted(names, key=lambda n: n.encode("utf-8")):
            bad("Z1", "<zip>", "entries are not sorted by path")
        corrupt = zf.testzip()
        if corrupt is not None:
            bad("Z1", corrupt, "CRC mismatch")
            return problems
        have = set(names)

        def read(name: str) -> bytes:
            return zf.read(name)

        # -- Z2 -----------------------------------------------------------------------------
        manifest: Manifest | None = None
        if "manifest.json" not in have:
            bad("Z2", "manifest.json", "missing")
        else:
            try:
                raw = json.loads(read("manifest.json").decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                bad("Z2", "manifest.json", f"not JSON: {exc}")
                raw = None
            if raw is not None:
                for msg in _jsonschema_problems(raw, schema_path):
                    bad("Z2", "manifest.json", f"schema: {msg}")
                try:
                    manifest = Manifest.model_validate(raw)
                except ValidationError as exc:
                    bad("Z2", "manifest.json", f"contract: {exc.errors()[0]['msg']}")
        # -- Z8 (README needs only the manifest's count) -------------------------------------
        if "README.md" not in have or not read("README.md").strip():
            bad("Z8", "README.md", "missing or empty")
        elif manifest is not None:
            count = len(manifest.articles)
            readme = read("README.md").decode("utf-8", "replace")
            if not re.search(rf"\b{count} articles?\b", readme):
                bad("Z8", "README.md", f"does not mention the article count ({count})")
        if manifest is None:
            return problems
        _check_articles_and_figures(zf, have, manifest, bad)
    return problems


def _check_articles_and_figures(
    zf: zipfile.ZipFile, have: set[str], manifest: Manifest, bad: Any
) -> None:
    def read(name: str) -> bytes:
        return zf.read(name)

    fig_ids = {f.id for f in manifest.figures}
    art_paths = {a.path for a in manifest.articles}
    zip_articles = {n for n in have if _ARTICLE_NAME.match(n)}
    # -- Z3 ---------------------------------------------------------------------------------
    for n in sorted(zip_articles ^ art_paths):
        bad("Z3", n, "article is not in both the zip and the manifest")
    refs: dict[str, list[str]] = {}  # article id -> figure ids of its figure lines, in order
    over_counts: dict[str, int] = {}  # article id -> frontmatter review.overrides
    sidecars: dict[str, FigureRecord] = {}
    for f in manifest.figures:
        if f.sidecar not in have:
            continue
        try:
            sidecars[f.id] = FigureRecord.model_validate_json(read(f.sidecar))
        except ValidationError as exc:
            bad("Z4", f.sidecar, f"sidecar does not validate: {exc.errors()[0]['msg']}")
    checked_images: set[str] = set()
    for a in manifest.articles:
        if a.path not in have:
            continue
        text = read(a.path).decode("utf-8")
        try:
            fm_raw, body = split_article(text)
        except (ValueError, yaml.YAMLError) as exc:
            bad("Z3", a.path, f"frontmatter: {exc}")
            continue
        if list(fm_raw) != KEYS:
            bad("Z3", a.path, f"frontmatter keys {list(fm_raw)} are not exactly {KEYS}")
        try:
            fm = ArticleFrontmatter.model_validate(fm_raw)
        except ValidationError as exc:
            bad("Z3", a.path, f"frontmatter does not validate: {exc.errors()[0]['msg']}")
            fm = None
        line_figs: list[str] = []
        for line in body.split("\n"):
            if not line.startswith("![FIG-"):
                continue
            m = FIGURE_LINE_RE.match(line)
            if m is None:
                bad("Z4", a.path, f"malformed figure reference: {line[:100]!r}")
                continue
            fid, img = m.group("fid"), m.group("path")
            line_figs.append(fid)
            if img not in have:
                bad("Z4", a.path, f"{fid}: image {img} is not in the zip")
            elif img not in checked_images:
                checked_images.add(img)
                msg = _check_image(img, read(img))
                if msg:
                    bad("Z4", img, msg)
            sc = sidecars.get(fid)
            sc_path = f"images/{ids.parse_figure_id(fid)[0]}/{fid}.json"
            if sc_path not in have:
                bad("Z4", a.path, f"{fid}: no sidecar {sc_path} in the zip")
            elif sc is None:
                pass  # already reported as an invalid sidecar
            else:
                target = posixpath.normpath(f"images/{sc.source_doc}/{sc.file}")
                if target != img:
                    bad("Z4", a.path, f"{fid}: sidecar file {target} != Markdown path {img}")
        refs[a.id] = line_figs
        # -- Z5 -----------------------------------------------------------------------------
        for m2 in ids.FIGURE_ID_SEARCH_RE.finditer(body):
            if m2.group(0) not in fig_ids:
                bad("Z5", a.path, f"{m2.group(0)} is mentioned but is not in manifest.figures")
        first_seen = list(dict.fromkeys(line_figs))
        if fm is not None:
            if fm.figures != first_seen:
                bad("Z5", a.path, f"frontmatter.figures {fm.figures} != body order {first_seen}")
            if fm.blocks != len(a.block_ids):
                bad("Z3", a.path, f"blocks {fm.blocks} != manifest {len(a.block_ids)}")
            for key, mine, theirs in (
                ("pages", fm.pages, a.pages),
                ("sections", fm.sections, a.sections),
                ("figures", fm.figures, a.figures),
            ):
                if mine != theirs:
                    bad("Z3", a.path, f"{key} {mine} != manifest {theirs}")
            if fm.generated_at != manifest.project.generated_at:
                bad("Z3", a.path, "generated_at differs from manifest.project.generated_at")
            if fm.id != a.id or fm.title != a.title or fm.source_doc != a.source_doc:
                bad("Z3", a.path, "id/title/source_doc differ from the manifest")
            over_counts[a.id] = fm.review.overrides
    # -- Z6 ---------------------------------------------------------------------------------
    zip_sidecars = {
        m.group("fid") for n in have if (m := _IMAGE_NAME.match(n)) and m.group("ext") == "json"
    }
    for fid in sorted(zip_sidecars ^ fig_ids):
        bad("Z6", fid, "figure is not in both the zip sidecars and manifest.figures")
    targets: set[str] = set()
    canon_has_file: dict[str, bool] = {}
    for f in manifest.figures:
        sc = sidecars.get(f.id)
        if sc is None:
            continue
        for rel in (sc.file, sc.svg):
            if rel is not None:
                targets.add(posixpath.normpath(f"images/{sc.source_doc}/{rel}"))
        for art in sc.articles:
            if art not in {a.id for a in manifest.articles}:
                bad("Z6", f.sidecar, f"articles lists {art}, which is not in the manifest")
            elif f.id not in refs.get(art, []):
                bad("Z6", f.sidecar, f"article {art} does not reference {f.id}")
        own_png = f"images/{f.source_doc}/{f.id}.png"
        if f.duplicate_of is not None and own_png in have:
            bad("Z6", own_png, f"{f.id} is a duplicate of {f.duplicate_of} and has its own file")
        if f.duplicate_of is None:
            canon_has_file[f.id] = own_png in have
    for fid, ok in canon_has_file.items():
        if not ok:
            bad("Z6", fid, "canonical figure has no image file")
    for n in sorted(have):
        m3 = _IMAGE_NAME.match(n)
        if m3 and m3.group("ext") in ("png", "svg") and n not in targets:
            bad("Z6", n, "orphan image: no sidecar points at it")
    # -- Z7 ---------------------------------------------------------------------------------
    per_article = sum(over_counts.get(a.id, 0) for a in manifest.articles)
    if not (per_article == manifest.review_stats.overrides == len(manifest.overrides)):
        bad(
            "Z7",
            "manifest.json",
            f"override counts differ: articles {per_article}, review_stats "
            f"{manifest.review_stats.overrides}, overrides {len(manifest.overrides)}",
        )
    in_articles = {b for a in manifest.articles for b in a.block_ids}
    for o in manifest.overrides:
        if o.target_id not in in_articles:
            bad(
                "Z7", "manifest.json", f"override target {o.target_id} is not a block of an article"
            )
