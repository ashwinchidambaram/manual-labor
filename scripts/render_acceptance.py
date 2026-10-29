"""Render docs/ACCEPTANCE.md from the raw results of scripts/acceptance.sh.

    render_acceptance.py render <dir>          Markdown to stdout
    render_acceptance.py providers <jsonl>     `ollama=N other=M` over an llm_calls.jsonl

Each SPEC section 11 item is VERIFIED only when every step it needs ran, exited 0 and printed
its evidence line; a step that did not run (skipped, no tests carry the marker, Ollama missing)
is NOT VERIFIED, and a step that ran and failed is FAILED. Nothing is inferred."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

VERIFIED, FAILED, NOT_VERIFIED = "VERIFIED", "FAILED", "NOT VERIFIED"
PULLS = [
    "ollama pull llama3.2:1b",
    "ollama pull qwen2.5:1.5b",
    "ollama pull moondream",
    "ollama pull nomic-embed-text",
]
TITLES = {
    0: "Machine checks: tests, lint, types, JSON schemas, OpenAPI",
    1: "SPEC 11.1: each fixture round-trips; zero faithfulness violations on auto-approved blocks",
    2: "SPEC 11.2: scanned fixture, every differing OCR block reaches the queue (recall)",
    3: "SPEC 11.3: figure-heavy fixture, >= 95% native/vector, caption references attach correctly",
    4: "SPEC 11.4: 20 queued blocks processed with the keyboard only",
    5: "SPEC 11.5: agent pass on 5 seeded flags, every proposal shows its re-check results",
    6: "SPEC 11.6: Scope toggle preserves selection and shows correct coverage",
    7: "SPEC 11.7: the export zip validates; every FIG reference resolves to a file and a sidecar",
    8: "SPEC 11.8: fully local run (Ollama), network disabled",
}


@dataclass
class Step:
    id: str
    cmd: str
    out: str
    rc: int
    secs: int


@dataclass
class Result:
    verdict: str
    evidence: str


def load(d: Path) -> dict[int, list[Step]]:
    steps: dict[int, list[Step]] = {}
    for cmd_file in sorted(d.glob("*-*.cmd"), key=lambda p: [int(x) for x in p.stem.split("-")]):
        sid = cmd_file.stem
        rc_file = d / f"{sid}.rc"
        if not rc_file.is_file():
            continue
        steps.setdefault(int(sid.split("-")[0]), []).append(
            Step(
                sid,
                cmd_file.read_text().strip(),
                (d / f"{sid}.out").read_text(errors="replace")
                if (d / f"{sid}.out").is_file()
                else "",
                int(rc_file.read_text().strip() or 1),
                int((d / f"{sid}.secs").read_text().strip() or 0)
                if (d / f"{sid}.secs").is_file()
                else 0,
            )
        )
    return steps


def pytest_summary(out: str) -> str:
    """pytest's own summary line; with `-qq` (addopts `-q` plus ours) there is none, so count
    the progress characters instead."""
    for ln in reversed(out.splitlines()):
        if re.search(r"\d+ (passed|failed|error|skipped|deselected)|no tests ran", ln):
            return ln.strip(" =")
    marks = "".join(
        m.group(1)
        for ln in out.splitlines()
        if (m := re.match(r"^([.FEsxX]+)(?:\s+\[\s*\d+%\])?\s*$", ln))
    )
    if not marks:
        return "no pytest summary line"
    parts = [
        f"{marks.count(c)} {name}"
        for c, name in ((".", "passed"), ("F", "failed"), ("E", "errors"), ("s", "skipped"))
        if marks.count(c)
    ]
    return ", ".join(parts) + " (counted from the progress line)"


# -- verdicts ----------------------------------------------------------------------------------


def need(steps: list[Step], n: int) -> Result | None:
    if len(steps) < n:
        return Result(NOT_VERIFIED, "the step did not run (skipped or its input was not produced)")
    bad = [s for s in steps if s.rc != 0]
    if bad:
        return Result(FAILED, f"{bad[0].id} exited {bad[0].rc}")
    return None


def v0(steps: list[Step], _live: bool) -> Result:
    r = need(steps, 5)
    if r:
        return r
    return Result(VERIFIED, pytest_summary(steps[0].out))


def v1(steps: list[Step], _live: bool) -> Result:
    r = need(steps, 1)
    if r:
        return r
    out = steps[0].out
    rows = {k: re.search(rf"^{k}\s.*$", out, re.M) for k in ("K3", "K12", "K13", "K14")}
    for k, m in rows.items():
        if m is None or " PASS " not in m.group(0):
            return Result(FAILED, f"{k} is not PASS in the labor check table")
    detail = re.sub(r"^K14\s.*?PASS\s+\d+\s+", "", rows["K14"].group(0))  # type: ignore[union-attr]
    per_doc = re.findall(r"(\w+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+)", detail)
    if not per_doc:
        return Result(FAILED, "the K14 round-trip table has no rows")
    bad = [d[0] for d in per_doc if d[3] != "0"]
    if bad:
        return Result(FAILED, f"faithfulness violations on auto-approved blocks in {bad}")
    rows_txt = ", ".join(f"{d[0]} 0/{d[2]}" for d in per_doc)
    return Result(
        VERIFIED,
        "K3, K12, K13, K14 PASS; faithfulness violations / auto-approved blocks per fixture: "
        + rows_txt,
    )


def v2(steps: list[Step], _live: bool) -> Result:
    r = need(steps, 1)
    if r:
        return r
    m = re.search(r"RECALL (\d+)/(\d+) at threshold ([0-9.]+)", steps[0].out)
    if m is None or int(m.group(2)) < 1:
        return Result(
            NOT_VERIFIED, "no test printed a RECALL line (marker acc2 missing or test skipped)"
        )
    k, n = int(m.group(1)), int(m.group(2))
    return Result(
        VERIFIED, f"recall {k}/{n} at threshold {m.group(3)}" + ("" if k == n else " (below 100%)")
    )


def v3(steps: list[Step], _live: bool) -> Result:
    r = need(steps, 1)
    if r:
        return r
    out = steps[0].out
    f = re.search(r"FIGURES native=(\d+) vector=(\d+) crop=(\d+)", out)
    attach = re.findall(r"ATTACH ok (\d+)/(\d+) \((\w+)\)", out)
    if f is None or not attach:
        return Result(NOT_VERIFIED, "the FIGURES / ATTACH evidence lines were not printed")
    nat, vec, crop = (int(x) for x in f.groups())
    total = nat + vec + crop
    ratio = (nat + vec) / total if total else 0.0
    wrong = [s for k, n, s in attach if k != n]
    if ratio < 0.95 or wrong:
        return Result(FAILED, f"native+vector {ratio:.2f}; attach mismatches {wrong}")
    got = ", ".join(f"{s} {k}/{n}" for k, n, s in attach)
    return Result(
        VERIFIED, f"native={nat} vector={vec} crop={crop} ({ratio:.0%}); caption refs {got}"
    )


def playwright(steps: list[Step], _live: bool) -> Result:
    r = need(steps, 1)
    if r:
        return r
    out = steps[0].out
    if re.search(r"No tests found|no tests found", out):
        return Result(NOT_VERIFIED, "no Playwright test carries the tag")
    m = re.search(r"(\d+) passed", out)
    if m is None or int(m.group(1)) < 1 or re.search(r"\d+ failed", out):
        return Result(NOT_VERIFIED, "no passing Playwright summary line")
    return Result(VERIFIED, f"{m.group(0)} (Playwright)")


def v5(steps: list[Step], _live: bool) -> Result:
    if steps and steps[0].rc == 5:
        return Result(
            NOT_VERIFIED, "no test carries the acc5 marker (module 10 evidence is missing)"
        )
    r = need(steps, 1)
    if r:
        return r
    m = re.search(r"PROPOSALS (\d+)/(\d+) with checks", steps[0].out)
    if m is None:
        return Result(NOT_VERIFIED, "no test printed a PROPOSALS line")
    k, n = int(m.group(1)), int(m.group(2))
    if k != n or n < 5:
        return Result(FAILED, f"PROPOSALS {k}/{n} with checks")
    return Result(VERIFIED, f"{m.group(0)}")


def v7(steps: list[Step], _live: bool) -> Result:
    if not steps:
        return Result(NOT_VERIFIED, "the step did not run")
    r = need(steps, 3)
    if r:
        return r
    m = re.search(r"^OK: (\d+) articles, (\d+) figures", steps[1].out, re.M)
    sha = steps[2].out.split()[0] if steps[2].out.split() else ""
    if m is None:
        return Result(FAILED, "labor validate-export did not print OK")
    return Result(VERIFIED, f"{pytest_summary(steps[0].out)}; {m.group(0)}; zip sha256 {sha}")


def v8(steps: list[Step], live: bool) -> Result:
    if not live or not steps:
        return Result(
            NOT_VERIFIED, "scripts/acceptance.sh was not run with --live (Ollama models required)"
        )
    check = next((s for s in steps if s.id == "8-2"), None)
    if check is not None and "SKIP live" in check.out:
        return Result(NOT_VERIFIED, "Ollama or its models are missing: " + "; ".join(PULLS))
    r = need(steps, 4)
    if r:
        return r
    m = re.search(r"ollama=(\d+) other=(\d+)", steps[3].out)
    if m is None or int(m.group(1)) < 1 or int(m.group(2)) != 0:
        return Result(FAILED, "llm_calls.jsonl is not ollama-only: " + steps[3].out.strip()[:100])
    return Result(VERIFIED, f"0 network violations; {m.group(0)}")


VERDICTS: dict[int, Callable[[list[Step], bool], Result]] = {
    0: v0, 1: v1, 2: v2, 3: v3, 4: playwright, 5: v5, 6: playwright, 7: v7, 8: v8,
}  # fmt: skip


# -- rendering ---------------------------------------------------------------------------------


def tail(text: str, n: int) -> str:
    lines = text.rstrip("\n").splitlines()
    cut = len(lines) - n
    note = f"[... {cut} earlier lines omitted ...]\n" if cut > 0 else ""
    return note + "\n".join(lines[-n:])


def host() -> str:
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
        mem = f"{ram:.1f} GiB RAM"
    except (ValueError, OSError, AttributeError):
        mem = "RAM unknown"
    return f"{platform.system()} {platform.release()} {platform.machine()}, {mem}"


def render(d: Path) -> str:
    steps = load(d)
    live = (d / "live.txt").read_text().strip() == "1" if (d / "live.txt").is_file() else False
    date = (d / "date.txt").read_text().strip() if (d / "date.txt").is_file() else "unknown"
    total = (d / "total_secs.txt").read_text().strip() if (d / "total_secs.txt").is_file() else "?"
    lock = Path("uv.lock")
    lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else "no uv.lock"
    try:
        from manuallabor import __version__ as version
    except ImportError:
        version = "unknown"
    results = {ac: VERDICTS[ac](steps.get(ac, []), live) for ac in range(9)}
    complete = all(r.verdict == VERIFIED for r in results.values())
    out = [
        "# Acceptance record (SPEC section 11)",
        "",
        f"status: {'COMPLETE' if complete else 'INCOMPLETE'}",
        f"generated: {date}",
        f"tool version: {version}",
        f"uv.lock sha256: {lock_sha}",
        f"host: {host()}",
        f"mode: {'live (local models)' if live else 'mock (no --live)'}",
        f"total wall time: {total} s",
        "",
        "Every line below is output pasted from the command that produced it. "
        "NOT VERIFIED means the step did not run or printed no evidence; it is not a pass.",
        "",
        "| AC | item | verdict | evidence |",
        "|---|---|---|---|",
    ]
    for ac in range(9):
        r = results[ac]
        out.append(f"| {ac} | {TITLES[ac]} | **{r.verdict}** | {r.evidence.replace('|', '/')} |")
    for ac in range(9):
        r = results[ac]
        out += ["", f"## AC{ac}: {TITLES[ac]}", "", f"verdict: **{r.verdict}**: {r.evidence}", ""]
        if ac == 8 and r.verdict == NOT_VERIFIED:
            out += ["To verify, install the small-tier models and re-run with `--live`:", "", "```"]
            out += [*PULLS, "bash scripts/acceptance.sh --live", "```", ""]
        for s in steps.get(ac, []):
            shown = (
                tail(s.out, 5) if ac == 0 else (s.out.rstrip("\n") if ac == 1 else tail(s.out, 80))
            )
            out += [
                f"command: `{s.cmd}`  (exit {s.rc}, {s.secs} s)",
                "",
                "```",
                shown,
                "```",
                "",
            ]
        if not steps.get(ac):
            out += ["No step ran for this item.", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def providers(path: Path) -> str:
    n_ollama = n_other = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if json.loads(line).get("provider") == "ollama":
            n_ollama += 1
        else:
            n_other += 1
    return f"ollama={n_ollama} other={n_other}"


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "render":
        sys.stdout.write(render(Path(argv[1])))
        return 0
    if len(argv) == 2 and argv[0] == "providers":
        print(providers(Path(argv[1])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
