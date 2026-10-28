"""Test 24: header/footer detection."""

from __future__ import annotations

from manuallabor.contracts.enums import BlockType
from manuallabor.parse.headers import HFItem, detect_headers_footers
from manuallabor.parse.text import hf_key


def _items(
    texts: dict[int, str], y: float = 745.0, ocr: bool = False, jitter: float = 0.0
) -> list[HFItem]:
    out = []
    for k, (page, text) in enumerate(sorted(texts.items())):
        yy = y + (jitter if k % 2 else 0.0)
        out.append(
            HFItem(
                index=k,
                page=page,
                bbox=[72, yy, 120, yy + 9],
                text=text,
                hint=None,
                is_region=False,
                page_height=792.0,
                is_ocr=ocr,
            )
        )
    return out


def test_page_numbers_share_a_key() -> None:
    assert hf_key("Page 3") == hf_key("Page 4") == "page #"


def test_footers_detected() -> None:
    items = _items({p: f"Page {p}" for p in range(2, 13)})
    got = detect_headers_footers(items, 12)
    assert set(got.values()) == {BlockType.footer} and len(got) == 11


def test_short_documents_have_none() -> None:
    assert detect_headers_footers(_items({1: "Page 1", 2: "Page 2"}), 2) == {}


def test_y_jitter_disqualifies() -> None:
    items = _items({p: f"Page {p}" for p in range(1, 9)}, jitter=20.0)
    assert detect_headers_footers(items, 8) == {}


def test_ocr_noise_clusters() -> None:
    texts = {p: "Acme X200 Service Manual" for p in range(1, 9)}
    texts[3] = "Acme X2O0 Service Manual"
    texts[5] = "Acme X200 Servlce Manual"
    items = _items(texts, y=40.0, ocr=True)
    got = detect_headers_footers(items, 8)
    assert len(got) == 8 and set(got.values()) == {BlockType.header}


def test_docling_hint_alone_in_short_doc() -> None:
    it = HFItem(0, 1, [72, 30, 150, 40], "Top", "page_header", False, 792.0, False)
    assert detect_headers_footers([it], 1) == {0: BlockType.header}
