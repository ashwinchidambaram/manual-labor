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
from manuallabor.contracts.article import TEXT_PREFIX, ArticleFrontmatter, ArticleReview
from manuallabor.contracts.figure import FigureRecord
from manuallabor.contracts.manifest import Manifest
from manuallabor.export.markers import (
    MARKER_LIKE_RE,
    STATUS_WORD,
    misplaced_markers,
    needs_marker,
    parse_marker,
    tally_markers,
)
from manuallabor.export.readme import tally_sentence
from manuallabor.export.render import FIGURE_LINE_RE
from manuallabor.export.types import Problem

__all__ = ["markdown_images", "split_article", "validate_zip"]

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
_REVIEW_NAME: Final = re.compile(rf"^articles/{_SLUG}(?:--{_SLUG})?\.review\.json$")
_IMAGE_NAME: Final = re.compile(
    rf"^images/(?P<slug>{_SLUG})/(?P<fid>FIG-[a-z0-9-]+-p\d{{3,4}}-\d{{2,3}})\.(?P<ext>png|svg|json)$"
)
SCHEMA_PATH: Final = Path(__file__).resolve().parents[2] / "schemas" / "Manifest.json"
_ALT_RE: Final = re.compile(r"^(?P<fid>FIG-[a-z0-9-]+-p\d{3,4}-\d{2,3}) \u2014 .+$", re.S)


def markdown_images(body: str) -> list[tuple[str, str]]:
    """(raw alt text, destination) of every Markdown image in `body`, found by a CommonMark
    parser (inline, reference-style, in quotes or lists), not by matching line starts."""
    from markdown_it import MarkdownIt

    out: list[tuple[str, str]] = []

    def walk(tokens: Any) -> None:
        for t in tokens:
            if t.type == "image":
                out.append((t.content, str(t.attrs.get("src") or "")))
            if t.children:
                walk(t.children)

    walk(MarkdownIt("commonmark").parse(body))
    return out


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
                or _REVIEW_NAME.match(n)
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
    over_counts: dict[str, int] = {}  # article id -> frontmatter review.overridden
    sidecars: dict[str, FigureRecord] = {}
    for f in manifest.figures:
        if f.sidecar not in have:
            continue
        try:
            sidecars[f.id] = FigureRecord.model_validate_json(read(f.sidecar))
        except ValidationError as exc:
            bad("Z4", f.sidecar, f"sidecar does not validate: {exc.errors()[0]['msg']}")
    checked_images: set[str] = set()
    reviews: list[ArticleReview] = []  # the sidecars that validate, for the README tally
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
        line_refs: set[tuple[str, str]] = set()
        for line in body.split("\n"):
            if not line.startswith("![FIG-"):
                continue
            m = FIGURE_LINE_RE.match(line)
            if m is None:
                bad("Z4", a.path, f"malformed figure reference: {line[:100]!r}")
                continue
            fid, img = m.group("fid"), m.group("path")
            line_figs.append(fid)
            line_refs.add((fid, img))
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
        # every other Markdown image whose target is under images/ (mid-line, quoted, listed,
        # reference-style): it must resolve and be a figure reference of the contracted form
        for alt, src in markdown_images(body):
            target = posixpath.normpath(src) if src else ""
            if target != "images" and not target.startswith("images/"):
                continue  # source text may link elsewhere; the body stays verbatim
            am = _ALT_RE.match(alt)
            if am is not None and (am.group("fid"), src) in line_refs:
                continue  # a figure line, checked above
            if target not in have:
                bad("Z4", a.path, f"image link {src} is not in the zip")
            if am is None:
                bad(
                    "Z4",
                    a.path,
                    f"image link {src}: alt {alt[:60]!r} is not `FIG-ID \u2014 caption`",
                )
            else:
                bad("Z4", a.path, f"{am.group('fid')}: image link {src} is not a figure line")
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
            over_counts[a.id] = fm.review.overridden
        rv = _check_review(zf, have, manifest, a, fm_raw, body, bad)
        if rv is not None:
            reviews.append(rv)
    # -- Z8 (the README's tally of markers and figure blocks, design 11 section 20.11) --------
    if len(reviews) == len(manifest.articles) and "README.md" in have:
        sentence = tally_sentence(tally_markers(reviews))
        if sentence not in read("README.md").decode("utf-8", "replace"):
            bad("Z8", "README.md", f"does not state this export's review tally: {sentence!r}")
    # -- Z9 (the review sidecar files themselves) --------------------------------------------
    zip_reviews = {n for n in have if _REVIEW_NAME.match(n)}
    for n in sorted(zip_reviews - {a.review_sidecar for a in manifest.articles}):
        bad("Z9", n, "review sidecar of no article in the manifest")
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


def _check_review(
    zf: zipfile.ZipFile,
    have: set[str],
    manifest: Manifest,
    a: Any,
    fm_raw: dict[str, Any],
    body: str,
    bad: Any,
) -> ArticleReview | None:
    """Z9 (design 11 sections 20.5 and 20.11): the article's review sidecar, its markers, its
    front matter counts and the manifest's overrides agree."""
    where = a.path
    if a.review_sidecar not in have:
        bad("Z9", a.review_sidecar, f"review sidecar of {a.id} is missing")
        rv = None
    else:
        try:
            rv = ArticleReview.model_validate_json(zf.read(a.review_sidecar))
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = "/".join(map(str, err["loc"]))
            bad("Z9", a.review_sidecar, f"sidecar does not validate: {loc}: {err['msg']}")
            rv = None
    lines = [ln for ln in body.split("\n") if MARKER_LIKE_RE.search(ln)]
    malformed = {ln for ln in lines if MARKER_LIKE_RE.match(ln) and parse_marker(ln) is None}
    for ln in sorted(malformed):
        bad("Z9", where, f"malformed marker: {ln[:120]!r}")
    # markers that a renderer would show, whatever the sidecar says
    for line, kind in misplaced_markers(body):
        if kind == "html_block" and line in malformed:
            continue  # its own block, only malformed: reported once above
        holder = {"fence": "a code fence", "code_block": "an indented code block"}.get(
            kind, f"a {kind.replace('_', ' ')}"
        )
        bad(
            "Z9",
            where,
            f"marker is not its own HTML block (it is inside {holder} and would render as "
            f"text): {line[:120]!r}",
        )
    markers = [mk for ln in lines if (mk := parse_marker(ln)) is not None]
    if rv is None:
        return None
    if rv.article_id != a.id or rv.article != a.path:
        bad("Z9", a.review_sidecar, f"article {rv.article_id} / {rv.article} is not {a.id}")
    if rv.generated_at != manifest.project.generated_at:
        bad("Z9", a.review_sidecar, "generated_at differs from manifest.project.generated_at")
    ids_ = [b.block_id for b in rv.blocks]
    if ids_ != a.block_ids:
        missing = [b for b in a.block_ids if b not in set(ids_)]
        extra = [b for b in ids_ if b not in set(a.block_ids)]
        if missing:
            bad("Z9", a.review_sidecar, f"blocks missing from the sidecar: {missing[:10]}")
        if extra:
            bad("Z9", a.review_sidecar, f"blocks not in the article: {extra[:10]}")
        if not missing and not extra:
            bad("Z9", a.review_sidecar, "blocks are not in the article's block order")
    entry = {b.block_id: b for b in rv.blocks}
    seen: dict[str, int] = {}
    for mk in markers:
        seen[mk.block_id] = seen.get(mk.block_id, 0) + 1
        e = entry.get(mk.block_id)
        if e is None:
            bad("Z9", where, f"marker for {mk.block_id}, which is not in the sidecar")
            continue
        if not needs_marker(e):
            bad(
                "Z9",
                where,
                f"{mk.block_id}: marker says {STATUS_WORD[mk.status]}, sidecar says a figure "
                "block (no marker expected)",
            )
            continue
        if mk.status != e.status:
            bad(
                "Z9",
                where,
                f"{mk.block_id}: marker says {STATUS_WORD[mk.status]}, sidecar says "
                f"{STATUS_WORD[e.status]}",
            )
        if mk.reason != e.reason:
            bad("Z9", where, f"{mk.block_id}: marker reason {mk.reason!r} != sidecar {e.reason!r}")
        if mk.flag_id != e.flag_id:
            bad("Z9", where, f"{mk.block_id}: marker flag {mk.flag_id} != sidecar {e.flag_id}")
    reported = _check_alignment(body, rv, where, bad)
    for e in rv.blocks:
        if not needs_marker(e):
            continue
        n = seen.get(e.block_id, 0)
        if n == 0 and e.block_id not in reported:
            bad("Z9", where, f"{e.block_id} is {STATUS_WORD[e.status]} but has no marker")
        elif n > 1:
            bad("Z9", where, f"{e.block_id} has {n} markers")
    # section 20.11: the front matter counts are the sidecar's, key for key. The raw mapping is
    # compared, so a mapping in other categories (the first version's `approved` that included
    # the checks) is reported by name even though it does not parse as the contract (Z3).
    want = rv.counts.model_dump()
    got = fm_raw.get("review")
    if not isinstance(got, dict):
        bad("Z9", where, f"front matter review {got!r} is not a mapping of counts")
    else:
        for key in sorted(set(got) | set(want)):
            mine, theirs = got.get(key, "missing"), want.get(key, "missing")
            if mine != theirs or type(mine) is not type(theirs):
                shown = mine if isinstance(mine, int) or mine == "missing" else repr(mine)
                bad("Z9", where, f"front matter review.{key} {shown} != review sidecar {theirs}")
    blocks = fm_raw.get("blocks")
    if blocks != len(rv.blocks) or type(blocks) is not int:
        bad("Z9", where, f"front matter blocks {blocks!r} != review sidecar {len(rv.blocks)}")
    overrides = {o.target_id: o for o in manifest.overrides}
    for e in rv.blocks:
        o = overrides.get(e.block_id)
        if e.status == "overridden":
            if o is None:
                bad(
                    "Z9",
                    a.review_sidecar,
                    f"{e.block_id} is overridden but not in manifest.overrides",
                )
            elif (o.reason, o.flag_id, o.at) != (e.reason, e.flag_id, e.at):
                bad(
                    "Z9",
                    a.review_sidecar,
                    f"{e.block_id}: reason, flag or time differ from manifest.overrides",
                )
        elif o is not None:
            bad("Z9", a.review_sidecar, f"{e.block_id} is in manifest.overrides but {e.status}")
        if e.figure is not None:
            _check_figure_status(zf, have, manifest, e, a.review_sidecar, bad)
            shown = sorted(x.id for x in manifest.articles if e.figure.figure_id in x.figures)
            placed = [p.article_id for p in e.figure.placements]
            if placed != shown:
                bad(
                    "Z9",
                    a.review_sidecar,
                    f"{e.figure.figure_id}: placements {placed} != articles showing it {shown}",
                )
    return rv


def _check_figure_status(
    zf: zipfile.ZipFile, have: set[str], manifest: Manifest, e: Any, where: str, bad: Any
) -> None:
    """A figure block's review status agrees with its figure's own sidecar `review`, when the
    figure is exported (an overridden figure block's figure keeps its queued/flagged status)."""
    mf = next((f for f in manifest.figures if f.id == e.figure.figure_id), None)
    if mf is None or mf.sidecar not in have:
        if e.figure.placements:
            bad("Z9", where, f"{e.figure.figure_id} is shown in an article but not exported")
        return
    try:
        rec = FigureRecord.model_validate_json(zf.read(mf.sidecar))
    except ValidationError:
        return  # reported by Z4
    ok = rec.review.value in ("queued", "flagged", "approved", "edited", "auto_approved")
    if e.status != "overridden":
        ok = rec.review.value == e.status
    if not ok:
        bad(
            "Z9",
            where,
            f"{e.block_id}: status {e.status} disagrees with {mf.sidecar} review "
            f"{rec.review.value}",
        )


def _check_alignment(body: str, rv: ArticleReview, where: str, bad: Any) -> set[str]:
    """Every text block's unit is in the body in sidecar order: its own marker line, `"\n"`,
    then its part, unchanged (its sha256), with the sidecar `text` its first 80 characters;
    figure lines may sit between units, nothing else (design 11 section 20.11). The body is
    `"\n# " + title + "\n"` then, when there are units, `"\n" + "\n\n".join(units) + "\n"`.
    Parts are matched by position, not by splitting on blank lines: a part may itself start or
    end with a newline, so it may end at any (overlapping) "\n\n" or at the end (20.10). Returns
    the block ids reported as having no marker directly before their paragraph."""
    import hashlib

    reported: set[str] = set()
    if not body.startswith("\n# "):
        return reported  # reported by Z3
    rest = body[body.index("\n", 1) + 1 :]
    if rest == "":
        content, n = "", -1  # no units at all: nothing can match
    elif len(rest) >= 2 and rest.startswith("\n") and rest.endswith("\n"):
        content = rest[1:-1]
        n = len(content)
    else:
        bad("Z9", where, "body is not a blank-line separated sequence of parts")
        return reported

    def line_at(at: int) -> tuple[str, int] | None:
        """The line starting at `at` and the offset of its end (its `\n`, or n)."""
        if at > n:
            return None
        end = content.find("\n", at)
        end = n if end < 0 else end
        return content[at:end], end

    def lone(at: int) -> tuple[str, int] | None:
        """A one-line unit at `at` (a figure line, or a marker standing alone), next start."""
        ln = line_at(at)
        if ln is None or (ln[1] != n and not content.startswith("\n\n", ln[1])):
            return None
        return ln[0], (ln[1] + 2 if ln[1] < n else n + 1)

    def match(start: int, digest: str) -> int | None:
        """Where the part with this sha256 that starts at `start` ends, if it does."""
        if start > n:
            return None
        h = hashlib.sha256()
        seg = j = start
        while True:
            k = content.find("\n\n", j)  # the next candidate end: an overlapping "\n\n", or n
            end = n if k < 0 else k
            h.update(content[seg:end].encode("utf-8"))
            seg = end
            if h.copy().hexdigest() == digest:
                return end
            if k < 0:
                return None
            j = k + 1

    def misplaced(block_id: str) -> None:
        bad("Z9", where, f"{block_id}: its marker is not directly before its paragraph")

    def unmarked(block_id: str) -> None:
        reported.add(block_id)
        bad("Z9", where, f"{block_id} has no marker directly before its paragraph")

    pos = 0  # start of the next unit; > n once the units are used up
    for e in rv.blocks:
        if e.text_sha256 is None:
            continue  # a figure block has no unit
        digest = e.text_sha256
        found: tuple[int, int] | None = None  # (start, end) of the part
        while found is None:
            one = lone(pos)
            if one is not None and FIGURE_LINE_RE.match(one[0]):
                pos = one[1]  # a figure line between units (every text unit starts with its marker)
                continue
            ln = line_at(pos)
            mk = parse_marker(ln[0]) if ln is not None else None
            if mk is not None and ln is not None:
                below = ln[1] + 1
                end = match(below, digest) if ln[1] < n else None
                if mk.block_id == e.block_id:
                    if end is not None:
                        found = (below, end)
                    elif one is not None and (end := match(one[1], digest)) is not None:
                        misplaced(e.block_id)  # a blank line between marker and paragraph
                        found = (one[1], end)
                    else:
                        break
                else:
                    misplaced(mk.block_id)
                    if end is not None:  # another block's marker above this paragraph
                        unmarked(e.block_id)
                        found = (below, end)
                    elif one is not None:
                        pos = one[1]  # a marker standing alone: look again after it
                    else:
                        break
            else:
                end = match(pos, digest)
                if end is None:
                    break
                unmarked(e.block_id)
                found = (pos, end)
        if found is None:
            bad(
                "Z9",
                where,
                f"{e.block_id}: its paragraph text is not in the article where the sidecar puts "
                "it (changed, moved or missing)",
            )
            return reported
        start, end = found
        if e.text != content[start:end][:TEXT_PREFIX]:
            bad(
                "Z9",
                where,
                f"{e.block_id}: its text in the review file is not the first {TEXT_PREFIX} "
                "characters of its paragraph",
            )
        pos = end + 2 if end < n else n + 1
    while pos <= n:
        one = lone(pos)
        if one is not None and FIGURE_LINE_RE.match(one[0]):
            pos = one[1]
            continue
        ln = line_at(pos)
        mk = parse_marker(ln[0]) if ln is not None else None
        if mk is not None:
            misplaced(mk.block_id)
            bad("Z9", where, f"marker of {mk.block_id} after the last paragraph")
        else:
            bad(
                "Z9",
                where,
                f"{content[pos : pos + 60]!r} after the last paragraph is not a figure line",
            )
        return reported
    return reported
