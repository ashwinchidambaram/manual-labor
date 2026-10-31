"""E17: validate_zip catches each defect by mutation, with the specific check's code."""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from manuallabor.export.types import Problem
from manuallabor.export.validate import validate_zip
from manuallabor.export.zip import write_zip
from tests.export.helpers import Exported

Files = dict[str, bytes]


def mutate(e: Exported, tmp: Path, fn: Callable[[Files], None]) -> list[Problem]:
    files: Files = {n: e.read(n) for n in e.names()}
    fn(files)
    out = tmp / "mutated.zip"
    write_zip(files, out)
    return validate_zip(out)


def codes(problems: list[Problem]) -> set[str]:
    return {p.code for p in problems}


def first_article(files: Files) -> str:
    return next(n for n in sorted(files) if n.startswith("articles/") and b"![FIG-" in files[n])


def first_figure_line(text: str) -> str:
    return next(ln for ln in text.split("\n") if ln.startswith("![FIG-"))


def edit_manifest(files: Files, fn: Callable[[dict], None]) -> None:  # type: ignore[type-arg]
    m = json.loads(files["manifest.json"])
    fn(m)
    files["manifest.json"] = (json.dumps(m, sort_keys=True, indent=2) + "\n").encode()


def test_the_unmodified_zip_is_valid(exported_a: Exported, tmp_path: Path) -> None:
    assert mutate(exported_a, tmp_path, lambda f: None) == []


def test_e17_a_missing_sidecar(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        side = next(n for n in sorted(f) if n.startswith("images/figures/") and n.endswith(".json"))
        del f[side]

    got = codes(mutate(exported_a, tmp_path, fn))
    assert {"Z4", "Z6"} <= got


def test_e17_a_figure_reference_to_a_missing_file(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        text = f[a].decode()
        line = first_figure_line(text)
        bad = line[: line.rindex("(")] + "(images/figures/FIG-figures-p098-97.png)"
        f[a] = text.replace(line, bad).encode()

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z4" in codes(problems)
    assert any("not in the zip" in p.detail or "!=" in p.detail for p in problems)


def test_e17_a_lost_article_in_the_manifest(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_manifest(f, lambda m: m["articles"].pop())

    assert "Z2" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_a_lost_block_in_the_accounting(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        def drop(m: dict) -> None:  # type: ignore[type-arg]
            acc = m["accounting"]
            bid = next(iter(acc["assignments"]))
            del acc["assignments"][bid]
            acc["unassigned_reasons"].pop(bid, None)

        edit_manifest(f, drop)

    assert "Z2" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_reordered_frontmatter_keys(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        lines = f[a].decode().split("\n")
        lines[1], lines[2] = lines[2], lines[1]  # id <-> title
        f[a] = "\n".join(lines).encode()

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z3" in codes(problems) and any("keys" in p.detail for p in problems)


def test_e17_a_stray_figure_id_in_prose(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        f[a] = f[a] + b"\nSee FIG-figures-p099-01 for details.\n"

    assert "Z5" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_an_orphan_image(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        png = next(n for n in sorted(f) if n.endswith(".png"))
        f["images/figures/FIG-figures-p098-01.png"] = f[png]

    got = codes(mutate(exported_a, tmp_path, fn))
    assert "Z6" in got


def test_e17_a_corrupt_png(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        line = first_figure_line(f[a].decode())
        path = line[line.rindex("(") + 1 : -1]
        f[path] = b"\x89PNG\r\n\x1a\nnot really a png"

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z4" in codes(problems) and any("decode" in p.detail for p in problems)


def test_e17_override_counts_must_agree(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        edit_manifest(f, lambda m: m["review_stats"].__setitem__("overrides", 1))

    assert "Z7" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_missing_readme(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        del f["README.md"]

    assert "Z8" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_readme_must_mention_the_article_count(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        f["README.md"] = b"# nothing here\n"

    assert "Z8" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_a_duplicate_with_its_own_image_file(exported_dup: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        png = next(n for n in sorted(f) if n.startswith("images/figures/") and n.endswith(".png"))
        dup = next(
            n for n in sorted(f) if n.startswith("images/figures-copy/") and n.endswith(".json")
        )
        f[dup.replace(".json", ".png")] = f[png]

    assert "Z6" in codes(mutate(exported_dup, tmp_path, fn))


def test_e17_structure_problems(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        f["notes/extra.txt"] = b"x"

    assert "Z1" in codes(mutate(exported_a, tmp_path, fn))
    # entries out of order
    out = tmp_path / "unsorted.zip"
    with zipfile.ZipFile(out, "w") as zf:
        for n in ("manifest.json", "README.md"):
            zf.writestr(n, exported_a.read(n))
    assert "Z1" in codes(validate_zip(out))
    # not a zip at all
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    assert [p.code for p in validate_zip(junk)] == ["Z1"]
    assert [p.code for p in validate_zip(tmp_path / "missing.zip")] == ["Z1"]


def test_e17_a_manifest_that_is_not_json(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        f["manifest.json"] = b"{not json"

    assert codes(mutate(exported_a, tmp_path, fn)) == {"Z2"}


@pytest.mark.parametrize("extra", ["schema"])
def test_e17_unknown_manifest_fields_fail_the_schema(
    exported_a: Exported, tmp_path: Path, extra: str
) -> None:
    def fn(f: Files) -> None:
        edit_manifest(f, lambda m: m.__setitem__("surprise", 1))

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z2" in codes(problems) and any(extra in p.detail for p in problems)


def test_e17_a_sidecar_that_names_an_article_that_does_not_reference_it(
    exported_a: Exported, tmp_path: Path
) -> None:
    def fn(f: Files) -> None:
        side = next(n for n in sorted(f) if n.startswith("images/figures/") and n.endswith(".json"))
        data = json.loads(f[side])
        other = next(
            n[len("articles/") : -3] for n in sorted(f) if n.startswith("articles/clean--")
        )
        data["articles"] = [other]  # a real article, but its body does not show this figure
        f[side] = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z6" in codes(problems) and any("does not reference" in p.detail for p in problems)


def test_e17_frontmatter_must_agree_with_the_manifest(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        text = f[a].decode()
        f[a] = re.sub(r"^blocks: \d+$", "blocks: 1", text, count=1, flags=re.M).encode()

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z3" in codes(problems) and any("blocks" in p.detail for p in problems)


def test_e17_an_invalid_sidecar(exported_a: Exported, tmp_path: Path) -> None:
    def fn(f: Files) -> None:
        side = next(n for n in sorted(f) if n.startswith("images/figures/") and n.endswith(".json"))
        f[side] = b'{"id": "FIG-figures-p001-01"}'

    assert "Z4" in codes(mutate(exported_a, tmp_path, fn))


def test_e17_a_figure_line_that_is_not_the_contracted_shape(
    exported_a: Exported, tmp_path: Path
) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        line = first_figure_line(f[a].decode())
        f[a] = f[a].replace(line.encode(), line.replace(" \u2014 ", " - ").encode())

    assert "Z4" in codes(mutate(exported_a, tmp_path, fn))


# -- every Markdown image link, not only lines that start with `![FIG-` (review fix) -------------


def figure_path(text: str) -> str:
    line = first_figure_line(text)
    return line[line.rindex("(") + 1 : -1]


def append_paragraph(f: Files, para: str) -> str:
    a = first_article(f)
    f[a] = f[a].rstrip(b"\n") + b"\n\n" + para.encode() + b"\n"
    return a


def test_z4_an_inline_image_under_images_that_does_not_resolve(
    exported_a: Exported, tmp_path: Path
) -> None:
    def fn(f: Files) -> None:
        append_paragraph(f, "See the drawing ![pump](images/figures/nope.png) for details.")

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z4" in codes(problems)
    assert any("images/figures/nope.png" in p.detail for p in problems)


def test_z4_an_image_under_images_without_the_figure_alt_form(
    exported_a: Exported, tmp_path: Path
) -> None:
    def fn(f: Files) -> None:
        path = figure_path(f[first_article(f)].decode())  # resolves: only the alt is wrong
        append_paragraph(f, f"![a photo of the pump]({path})")

    problems = mutate(exported_a, tmp_path, fn)
    assert "Z4" in codes(problems)
    assert any("alt" in p.detail for p in problems)


def test_z4_an_indented_or_quoted_figure_reference_is_checked_too(
    exported_a: Exported, tmp_path: Path
) -> None:
    def fn(f: Files) -> None:
        a = first_article(f)
        line = first_figure_line(f[a].decode())
        moved = line.replace(figure_path(f[a].decode()), "images/figures/FIG-figures-p098-97.png")
        append_paragraph(f, "> " + moved)

    assert "Z4" in codes(mutate(exported_a, tmp_path, fn))


def test_an_image_link_outside_images_in_source_text_is_left_alone(
    exported_a: Exported, tmp_path: Path
) -> None:
    def fn(f: Files) -> None:
        append_paragraph(f, "Source text with ![logo](https://example.com/logo.png) in it.")

    # no image problem; the appended paragraph belongs to no block, which Z9 reports (design
    # 11 section 20.10: every paragraph of an article is in its review sidecar)
    problems = mutate(exported_a, tmp_path, fn)
    assert "Z4" not in codes(problems)
    assert codes(problems) == {"Z9"}


def test_a_caption_with_brackets_and_parens_still_validates(
    exported_a: Exported, tmp_path: Path
) -> None:
    from manuallabor.export.render import alt_text

    def fn(f: Files) -> None:
        a = first_article(f)
        text = f[a].decode()
        line = first_figure_line(text)
        fid = line[2 : line.index(" — ")]
        alt = alt_text(fid, "Pump [see](images/figures/x.png) (rev. 2)", None)
        f[a] = text.replace(line, f"![{alt}]({figure_path(text)})").encode()

    assert mutate(exported_a, tmp_path, fn) == []
