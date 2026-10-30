"""Concurrent requests for the same page image must not collide on a shared temp file.

Seen live in module 13: the Verify screen's page strip and the source pane fetch the same page PNG
at once, and the second render failed with FileNotFoundError on os.replace because both wrote
`<out>.tmp`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from manuallabor.parse.render import render_page_png, render_tmp_path

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


def test_stray_tmp_cleaner_does_not_break_an_in_flight_page_render(tmp_path: Path) -> None:
    """API page renders run without the worker lock; a job's start-up cleaner may run beside one."""
    import threading
    import time

    from manuallabor.jobs.executor import clean_stray_tmp
    from manuallabor.project import ProjectPaths

    paths = ProjectPaths(tmp_path)
    out = paths.docs / "clean" / "pages_view" / "p001-200.png"
    out.parent.mkdir(parents=True)
    stop = threading.Event()
    errors: list[BaseException] = []

    def cleaner() -> None:
        while not stop.is_set():
            clean_stray_tmp(paths)

    threads = [threading.Thread(target=cleaner) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            out.unlink(missing_ok=True)
            try:
                render_page_png(FIXTURE, 0, 200, out)
            except FileNotFoundError as e:  # the cleaner removed the temp file under the renderer
                errors.append(e)
                break
    finally:
        stop.set()
        for t in threads:
            t.join()
    assert not errors, f"cleaner broke a render: {errors[0]}"
    assert out.is_file()


def test_cleaner_leaves_a_render_temp_file_alone(tmp_path: Path) -> None:
    from manuallabor.jobs.executor import clean_stray_tmp
    from manuallabor.project import ProjectPaths

    paths = ProjectPaths(tmp_path)
    out = paths.docs / "clean" / "pages_view" / "p001-150.png"
    out.parent.mkdir(parents=True)
    in_flight = render_tmp_path(out)
    in_flight.write_bytes(b"partial")
    stray = out.parent / "p002-150.png.tmp"
    stray.write_bytes(b"left by a kill")
    assert clean_stray_tmp(paths) == 1
    assert in_flight.is_file(), "an in-flight render was deleted"
    assert not stray.exists()
