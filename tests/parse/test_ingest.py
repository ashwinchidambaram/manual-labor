"""Tests 28 and 29: ingest and metadata."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pymupdf
import pytest

from manuallabor.contracts.config import ModelRef, ProjectConfig
from manuallabor.contracts.enums import DocKind, Task
from manuallabor.ingest import IngestError, ingest_files, sha256_file
from manuallabor.parse.metadata import find_product_model, infer_metadata
from manuallabor.project import ProjectPaths
from manuallabor.providers import ListSink, MockProvider
from tests.parse.conftest import ALL_FIXTURES, FILES, FIXTURES, Parsed
from tests.parse.gt import load_gt


def _project(tmp_path: Path) -> ProjectPaths:
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copyfile(FIXTURES / "project-a" / "project.json", root / "project.json")
    return ProjectPaths(root)


def test_28_ingest(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    sums = json.loads((FIXTURES / "CHECKSUMS.json").read_text())
    quiet = {"emit": lambda _o: None}
    for stem in ALL_FIXTURES:
        assert sha256_file(FIXTURES / FILES[stem]) == sums[FILES[stem]]
    res = {
        r.file: r for r in ingest_files(paths, [FIXTURES / FILES[k] for k in ALL_FIXTURES], **quiet)
    }
    for stem in ALL_FIXTURES:
        gt = load_gt(stem)
        r = res[FILES[stem]]
        assert r.slug == gt["expected_slug"] and r.status == "new"
    doc = paths.load_document
    assert (
        doc("clean").kind == DocKind.born_digital_pdf
        and doc("clean").pages_without_text_layer == []
    )
    assert doc("scanned").kind == DocKind.scanned_pdf
    assert doc("scanned").pages_without_text_layer == list(range(1, 13))
    assert doc("manual").kind == DocKind.docx and doc("manual").page_count == 2

    again = ingest_files(paths, [FIXTURES / "clean.pdf"], **quiet)
    assert again[0].status == "exists" and again[0].slug == "clean"

    copy = tmp_path / "clean-copy.pdf"
    shutil.copyfile(FIXTURES / "clean.pdf", copy)
    assert ingest_files(paths, [copy], **quiet)[0].slug == "clean-copy"

    changed = tmp_path / "other" / "clean.pdf"
    changed.parent.mkdir()
    with pymupdf.open(FIXTURES / "twocol.pdf") as d:
        d.save(changed)
    with pytest.raises(IngestError):
        ingest_files(paths, [changed], **quiet)


def test_28_mixed_document(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    mixed = tmp_path / "mixed.pdf"
    out = pymupdf.open()
    with pymupdf.open(FIXTURES / "clean.pdf") as a:
        out.insert_pdf(a, from_page=0, to_page=2)
    with pymupdf.open(FIXTURES / "scanned.pdf") as b:
        out.insert_pdf(b, from_page=3, to_page=5)
    out.save(mixed)
    out.close()
    ingest_files(paths, [mixed], emit=lambda _o: None)
    d = paths.load_document("mixed")
    assert d.kind == DocKind.born_digital_pdf and d.pages_without_text_layer == [4, 5, 6]


def test_29_metadata_matches_ground_truth(parsed: Parsed) -> None:
    for stem in ALL_FIXTURES:
        gt = load_gt(stem)
        d = parsed.doc(stem)
        assert d.title == gt["title"], stem
        assert d.product_model == gt["product_model"], stem
        assert d.product_model_inferred is False


def _provider(reply: str) -> MockProvider:
    return MockProvider(
        ModelRef(provider="mock", model="m"), sink=ListSink(), responses={Task.metadata: reply}
    )


def test_29_llm_fallback_accepts_only_grounded_values() -> None:
    warnings: list[str] = []
    text = "Ranger Pro mower guide"
    meta = infer_metadata(
        page1_lines=[],
        body=None,
        embedded_title=None,
        filename="guide.pdf",
        provider=_provider('{"title": null, "product_model": "Ranger Pro"}'),
        warn=warnings.append,
        page1_text=text,
    )
    assert meta.product_model == "Ranger Pro" and meta.product_model_inferred
    bad = infer_metadata(
        page1_lines=[],
        body=None,
        embedded_title=None,
        filename="guide.pdf",
        provider=_provider('{"title": null, "product_model": "Foo 3000"}'),
        warn=warnings.append,
        page1_text=text,
    )
    assert bad.product_model is None and not bad.product_model_inferred
    assert any("rejected" in w for w in warnings)


def test_29_model_heuristics() -> None:
    assert (
        find_product_model("Model X200 · Revision 4", "Acme X200 Service Manual", "a.pdf")
        == "Acme X200"
    )
    assert find_product_model("hello", None, "x200-guide.pdf") == "X200"
    assert find_product_model("hello", None, "ACME-2024-MANUAL.pdf") is None
    assert find_product_model("hello", None, "MANUAL-V2.pdf") is None
    assert find_product_model("hello", None, "service_guide_rev4.pdf") is None
    assert ProjectConfig(name="x").ocr_engine.value == "auto"


_TEXT = "Ranger Pro mower guide\nOwner handbook for the Ranger Pro 3000 series"


def _llm(canned: str, filename: str = "guide.pdf"):  # type: ignore[no-untyped-def]
    warnings: list[str] = []
    meta = infer_metadata(
        page1_lines=[],
        body=None,
        embedded_title=None,
        filename=filename,
        provider=_provider(canned),
        warn=warnings.append,
        page1_text=_TEXT + "\n" + " ".join(["mower"] * 40),
    )
    return meta, warnings


@pytest.mark.parametrize(
    "title,model",
    [
        ("e", "e"),  # single characters that occur in any text
        ("Ranger Pro mower guide\nOwner", "Ranger\nPro"),  # newlines
        (" ".join(["mower"] * 40), " ".join(["mower"] * 40)),  # 40-word fragments
        ("Ranger Pro mower guid", "Ranger Pr"),  # not whole-word sequences
        ("Zeta handbook", "Zeta 9000"),  # not in the page text
        ("Owner handbook for", "RP 3000!"),  # not model-shaped ("!") and absent
    ],
)
def test_29_llm_rejects_ungrounded_or_malformed(title: str, model: str) -> None:
    meta, warnings = _llm(json.dumps({"title": title, "product_model": model}))
    assert meta.product_model is None and not meta.product_model_inferred
    if title != "Owner handbook for":  # that one is a grounded, valid title
        assert meta.title is None and not meta.title_inferred
    assert warnings


def test_29_llm_title_is_marked_inferred() -> None:
    meta, _ = _llm('{"title": "Ranger Pro mower guide", "product_model": "Ranger Pro 3000"}')
    assert meta.title == "Ranger Pro mower guide" and meta.title_inferred
    assert meta.product_model == "Ranger Pro 3000" and meta.product_model_inferred


# code review F13 (design 07 section 15): failures that used to read as "nothing there"


def test_metadata_provider_says_why_when_project_json_is_unreadable(tmp_path: Path) -> None:
    from manuallabor.ingest import metadata_provider

    paths = _project(tmp_path)
    paths.config.write_text("{not json")
    warns: list[str] = []
    assert metadata_provider(paths, warns.append) is None
    assert len(warns) == 1 and "project.json could not be read" in warns[0]


def test_docx_info_does_not_hide_a_missing_python_docx(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from manuallabor.ingest import _docx_info

    monkeypatch.setitem(sys.modules, "docx", None)  # `import docx` raises ImportError
    with pytest.raises(ImportError):
        _docx_info(FIXTURES / "manual.docx")
