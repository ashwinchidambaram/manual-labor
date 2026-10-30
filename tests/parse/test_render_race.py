"""Concurrent requests for the same page image must not collide on a shared temp file.

Seen live in module 13: the Verify screen's page strip and the source pane fetch the same page PNG
at once, and the second render failed with FileNotFoundError on os.replace because both wrote
`<out>.tmp`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from manuallabor.parse.render import render_page_png

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "clean.pdf"


def test_concurrent_renders_of_one_page_all_succeed(tmp_path: Path) -> None:
    out = tmp_path / "pages_view" / "p001-72.png"
    for round_ in range(4):
        out.unlink(missing_ok=True)
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(lambda _: render_page_png(FIXTURE, 0, 72, out), range(6)))
        assert out.is_file() and out.stat().st_size > 0, f"round {round_}: no page image"
        assert any(results), f"round {round_}: nobody rendered"
        assert not list(out.parent.glob("*.tmp")), f"round {round_}: temp files left behind"
