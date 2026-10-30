"""Project paths come from `ProjectPaths` (code review F17): no module builds `.llm_cache`,
`llm_calls.jsonl` or `probe.json` by hand."""

from __future__ import annotations

import re
from pathlib import Path

from manuallabor.project import ProjectPaths

PKG = Path(__file__).resolve().parents[1] / "manuallabor"
HAND_BUILT = re.compile(r"""/\s*["'](\.llm_cache|llm_calls\.jsonl|probe\.json)["']""")


def test_project_paths_names_the_cache_log_and_probe(tmp_path: Path) -> None:
    p = ProjectPaths(tmp_path)
    assert p.llm_cache == tmp_path / ".llm_cache"
    assert p.llm_log == tmp_path / "llm_calls.jsonl"
    assert p.probe == tmp_path / "probe.json"


def test_no_module_builds_those_paths_by_hand() -> None:
    offenders = [
        f"{f.relative_to(PKG.parent)}:{i}: {line.strip()}"
        for f in sorted(PKG.rglob("*.py"))
        if f.name != "project.py"
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if HAND_BUILT.search(line)
    ]
    assert offenders == [], "\n".join(offenders)
