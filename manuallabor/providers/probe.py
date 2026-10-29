"""Hardware probe: detectors, pure parsers, suggestion rules, table rendering.

Never installs anything and never runs `ollama pull`; it only prints the commands."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from manuallabor.contracts.probe import (
    CpuInfo,
    GpuInfo,
    OllamaModel,
    OllamaStatus,
    PlatformInfo,
    ProbeResult,
    SpeedClass,
    SuggestionTable,
    TaskSuggestion,
    Tier,
    TierOption,
)
from manuallabor.providers.base import utc_now
from manuallabor.providers.probe_catalog import API, API_KEY_ENV, CATALOG, TASKS, Candidate
from manuallabor.providers.registry import normalize_ollama_host

Runner = Callable[[Sequence[str], float], str | None]
GIB = 1024**3
KV_OVERHEAD_GB = 1.5
DISK_RESERVE_GB = 5.0


def default_runner(cmd: Sequence[str], timeout: float = 3.0) -> str | None:
    try:
        r = subprocess.run(  # noqa: S603
            list(cmd), capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


# -- pure parsers ----------------------------------------------------------
@dataclass(frozen=True)
class SysctlInfo:
    cpu_model: str | None
    ram_bytes: int | None
    cores_physical: int | None
    cores_logical: int | None


def _int(s: str | None) -> int | None:
    try:
        return int((s or "").strip())
    except ValueError:
        return None


def parse_sysctl_macos(
    brand: str | None, memsize: str | None, physical: str | None, logical: str | None
) -> SysctlInfo:
    b = (brand or "").strip() or None
    return SysctlInfo(b, _int(memsize), _int(physical), _int(logical))


def parse_system_profiler(text: str | None) -> tuple[str | None, int | None]:
    """(chip name, GPU core count) from `system_profiler SPDisplaysDataType -json`."""
    try:
        data = json.loads(text or "")
        entry = data["SPDisplaysDataType"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return None, None
    name = entry.get("sppci_model") if isinstance(entry, dict) else None
    cores = _int(str(entry.get("sppci_cores"))) if isinstance(entry, dict) else None
    return (name if isinstance(name, str) else None), cores


def parse_nvidia_smi_csv(text: str | None) -> list[tuple[str, float]]:
    """[(name, vram_gb)] from `--query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    out: list[tuple[str, float]] = []
    for line in (text or "").splitlines():
        name, sep, mem = line.rpartition(",")
        if not sep:
            continue
        try:
            mib = float(mem.strip())
        except ValueError:
            continue
        if name.strip():
            out.append((name.strip(), mib / 1024.0))
    return out


def parse_rocm_smi_json(text: str | None) -> list[tuple[str, float]]:
    try:
        data = json.loads(text or "")
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, float]] = []
    for key in sorted(data):
        card = data[key]
        if not isinstance(card, dict) or not key.lower().startswith("card"):
            continue
        name = next(
            (
                str(v)
                for k, v in card.items()
                if k.lower() in ("card series", "card model", "card sku")
            ),
            key,
        )
        total = next(
            (_int(str(v)) for k, v in card.items() if "total memory" in k.lower()),
            None,
        )
        if total:
            out.append((name, total / GIB))
    return out


def parse_meminfo(text: str | None) -> float | None:
    m = re.search(r"^MemTotal:\s+(\d+)\s*kB", text or "", re.MULTILINE)
    return int(m.group(1)) * 1024 / GIB if m else None


def parse_cpuinfo(text: str | None) -> tuple[str | None, int | None]:
    t = text or ""
    m = re.search(r"^model name\s*:\s*(.+)$", t, re.MULTILINE)
    n = len(re.findall(r"^processor\s*:", t, re.MULTILINE)) or None
    return (m.group(1).strip() if m else None), n


def parse_ollama_tags(text: str | None) -> list[OllamaModel]:
    try:
        data = json.loads(text or "")
        items = data["models"]
    except (ValueError, KeyError, TypeError):
        return []
    out: list[OllamaModel] = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("name"), str):
            size = it.get("size")
            out.append(
                OllamaModel(
                    name=it["name"],
                    size_gb=(size / GIB) if isinstance(size, (int, float)) else 0.0,
                    digest=str(it.get("digest", ""))[:12],
                )
            )
    return out


# -- detection -------------------------------------------------------------
def effective_memory_gb(ram_gb: float, gpu: GpuInfo | None) -> float:
    if gpu is not None and gpu.vendor in ("nvidia", "amd") and gpu.vram_gb:
        return gpu.vram_gb
    if gpu is not None and gpu.vendor == "apple":
        return ram_gb * (0.66 if ram_gb <= 36 else 0.75)
    return ram_gb * 0.5


def _http_get(url: str, timeout: float) -> str | None:
    try:
        import httpx

        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def run_probe(
    *,
    runner: Runner | None = None,
    clock: Callable[[], datetime] = utc_now,
    path: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
    env: Mapping[str, str] | None = None,
    http_get: Callable[[str, float], str | None] = _http_get,
    read_text: Callable[[str], str | None] = _read_text,
    which: Callable[[str], str | None] = shutil.which,
    disk_free: Callable[[Path], float] | None = None,
    cpu_count: Callable[[], int | None] = os.cpu_count,
) -> ProbeResult:
    runner = runner or default_runner
    env = os.environ if env is None else env
    system = system or platform.system()
    machine = machine or platform.machine()
    path = path or Path.cwd()
    notes: list[str] = []

    cpu_model, phys, logical, ram_gb = "unknown", None, cpu_count(), 0.0
    gpu: GpuInfo | None = None

    if system == "Darwin":
        s = parse_sysctl_macos(
            runner(["sysctl", "-n", "machdep.cpu.brand_string"], 3.0),
            runner(["sysctl", "-n", "hw.memsize"], 3.0),
            runner(["sysctl", "-n", "hw.physicalcpu"], 3.0),
            runner(["sysctl", "-n", "hw.logicalcpu"], 3.0),
        )
        if s.ram_bytes is None:
            notes.append("sysctl hw.memsize unavailable; RAM unknown")
        cpu_model = s.cpu_model or "unknown"
        ram_gb = (s.ram_bytes or 0) / GIB
        phys, logical = s.cores_physical, s.cores_logical or logical
        if machine == "arm64" or cpu_model.startswith("Apple"):
            chip, cores = parse_system_profiler(
                runner(["system_profiler", "SPDisplaysDataType", "-json"], 8.0)
            )
            if chip is None:
                notes.append("system_profiler unavailable; GPU details skipped")
            name = chip or cpu_model
            if cores:
                name = f"{name} ({cores}-core GPU)"
            gpu = GpuInfo(vendor="apple", name=name, vram_gb=None, unified=True)
    elif system == "Linux":
        cpuinfo = read_text("/proc/cpuinfo")
        m, n = parse_cpuinfo(cpuinfo)
        cpu_model = m or "unknown"
        logical = n or logical
        mem = parse_meminfo(read_text("/proc/meminfo"))
        if mem is None:
            notes.append("/proc/meminfo unreadable; RAM unknown")
        ram_gb = mem or 0.0
        nv = parse_nvidia_smi_csv(
            runner(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                3.0,
            )
        )
        if nv:
            name, vram = max(nv, key=lambda t: t[1])
            gpu = GpuInfo(vendor="nvidia", name=name, vram_gb=vram, unified=False)
        else:
            amd = parse_rocm_smi_json(
                runner(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"], 3.0)
            )
            if amd:
                name, vram = max(amd, key=lambda t: t[1])
                gpu = GpuInfo(vendor="amd", name=name, vram_gb=vram, unified=False)
            else:
                notes.append("no nvidia-smi / rocm-smi GPU found; CPU-only")
    else:
        notes.append(f"unsupported platform {system!r}; only CPU and RAM are reported")
        try:
            import psutil  # type: ignore[import-untyped]

            ram_gb = psutil.virtual_memory().total / GIB
        except Exception:
            notes.append("psutil unavailable; RAM unknown")

    free = (
        disk_free(path)
        if disk_free
        else shutil.disk_usage(path if path.exists() else Path.cwd()).free / GIB
    )

    host = normalize_ollama_host(env.get("OLLAMA_HOST"))
    installed = which("ollama") is not None
    version = None
    if installed:
        raw = runner(["ollama", "--version"], 3.0)
        mv = re.search(r"(\d+\.\d+\.\d+\S*)", raw or "")
        version = mv.group(1) if mv else None
    tags = http_get(f"{host}/api/tags", 2.0)
    if tags is None:
        notes.append(f"Ollama not reachable at {host}")
    status = OllamaStatus(
        installed=installed,
        version=version,
        host=host,
        reachable=tags is not None,
        models=parse_ollama_tags(tags),
    )
    from manuallabor.providers.litellm_provider import litellm_version

    return ProbeResult(
        probed_at=clock(),
        platform=PlatformInfo(system=system, machine=machine),
        cpu=CpuInfo(
            model=cpu_model,
            cores_physical=phys if phys and phys > 0 else None,
            cores_logical=logical if logical and logical > 0 else None,
        ),
        ram_gb=ram_gb,
        gpu=gpu,
        effective_model_memory_gb=effective_memory_gb(ram_gb, gpu),
        disk_free_gb=free,
        disk_path=str(path),
        ollama=status,
        litellm_version=litellm_version(),
        notes=notes,
    )


# -- suggestions -----------------------------------------------------------
def _bandwidth_gbps(probe: ProbeResult) -> float:
    g = probe.gpu
    if g is None or g.vendor == "none":
        return 40.0
    if g.vendor == "apple":
        n = g.name.lower()
        for key, bw in (("ultra", 600.0), ("max", 300.0), ("pro", 150.0)):
            if re.search(rf"\b{key}\b", n):
                return bw
        return 100.0
    return 300.0


def _headroom_gb(probe: ProbeResult) -> float:
    g = probe.gpu
    return 1.0 if g is not None and g.vendor in ("nvidia", "amd") else 3.0


def _present(probe: ProbeResult, model: str) -> bool:
    names = {m.name for m in probe.ollama.models}
    return model in names or f"{model}:latest" in names


def _speed_class(fits: bool, tps: float | None) -> SpeedClass:
    if not fits or tps is None:
        return "n/a"
    return "fast" if tps >= 30 else "ok" if tps >= 10 else "slow"


def _option(probe: ProbeResult, c: Candidate, budget: float) -> TierOption:
    fits = c.approx_gb + KV_OVERHEAD_GB <= budget
    tps = round(0.5 * _bandwidth_gbps(probe) / c.approx_gb, 1) if c.approx_gb > 0 else None
    present = _present(probe, c.model)
    return TierOption(
        provider=c.provider,
        model=c.model,
        approx_gb=c.approx_gb,
        fits=fits,
        speed_class=_speed_class(fits, tps),
        est_tokens_per_s=tps,
        pull_command=None if present else f"ollama pull {c.model}",
        present=present,
        note=None,
    )


def _api_option(task: str) -> TierOption:
    c = API[task]
    return TierOption(
        provider=c.provider,
        model=c.model,
        approx_gb=0.0,
        fits=True,
        speed_class="fast",
        est_tokens_per_s=None,
        pull_command=None,
        present=True,
        note=f"needs {API_KEY_ENV[c.provider]}; data leaves the machine",
    )


def suggest(probe: ProbeResult) -> SuggestionTable:
    budget = probe.effective_model_memory_gb - _headroom_gb(probe)
    rows = [
        TaskSuggestion(
            task=t,  # type: ignore[arg-type]
            small=_option(probe, CATALOG[t]["small"], budget),
            medium=_option(probe, CATALOG[t]["medium"], budget),
            large=_option(probe, CATALOG[t]["large"], budget),
            api=_api_option(t),
        )
        for t in TASKS
    ]
    default: Tier = "small"
    if probe.effective_model_memory_gb >= 14:
        for tier in ("small", "medium", "large"):
            opts = [getattr(r, tier) for r in rows]
            uniq = {o.model: o for o in opts}
            fits_all = all(o.fits for o in opts)
            total = sum(o.approx_gb + KV_OVERHEAD_GB for o in uniq.values())
            missing = sum(o.approx_gb for o in uniq.values() if not o.present)
            if fits_all and total <= budget and missing <= probe.disk_free_gb - DISK_RESERVE_GB:
                default = tier
    pulls: dict[str, list[str]] = {}
    for tier in ("small", "medium", "large"):
        cmds = sorted({c for r in rows if (c := getattr(r, tier).pull_command)})
        pulls[tier] = cmds
    return SuggestionTable(default_tier=default, rows=rows, pull_commands=pulls)


def tier_models(table: SuggestionTable, tier: Tier) -> dict[str, dict[str, str]]:
    """{task: {"provider":..., "model":...}} for the five configurable tasks."""
    return {
        r.task: {
            "provider": getattr(r, tier).provider,
            "model": getattr(r, tier).model,
        }
        for r in table.rows
    }


def render_table(probe: ProbeResult, table: SuggestionTable, tier: Tier | None = None) -> str:
    gpu = probe.gpu.name if probe.gpu else "none (CPU only)"
    lines = [
        f"Platform : {probe.platform.system} {probe.platform.machine}",
        f"CPU      : {probe.cpu.model} ({probe.cpu.cores_physical or '?'} cores)",
        f"RAM      : {probe.ram_gb:.1f} GB   "
        f"usable for models: ~{probe.effective_model_memory_gb:.1f} GB",
        f"GPU      : {gpu}",
        f"Disk free: {probe.disk_free_gb:.1f} GB ({probe.disk_path})",
        "Ollama   : "
        + (
            f"{probe.ollama.version or 'installed'} at {probe.ollama.host}, "
            + ("reachable" if probe.ollama.reachable else "NOT reachable")
            if probe.ollama.installed
            else "not installed"
        ),
        "",
        f"Suggested tier: {table.default_tier}",
        "",
    ]

    def cell(o: TierOption) -> str:
        if o.provider in ("anthropic", "openai"):
            return f"{o.provider}:{o.model}"
        flag = "" if o.fits else " NO-FIT"
        miss = "" if o.present else " *"
        spd = (
            f" ~{o.est_tokens_per_s:g}t/s {o.speed_class}" if o.fits and o.est_tokens_per_s else ""
        )
        return f"{o.model} {o.approx_gb:g}G{spd}{flag}{miss}"

    header = ["task", "small", "medium", "large", "api"]
    body = [[r.task, cell(r.small), cell(r.medium), cell(r.large), cell(r.api)] for r in table.rows]
    widths = [max(len(row[i]) for row in [header, *body]) for i in range(5)]
    for row in [header, ["-" * w for w in widths], *body]:
        lines.append("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())
    lines += [
        "",
        "(* = not pulled yet; ~t/s is an estimate, not a measurement; api sends data off-machine)",
    ]
    lines += ["", "Commands to run yourself (labor never installs anything):"]
    shown = [tier] if tier else [table.default_tier]
    cmds = [c for t in shown if t != "api" for c in table.pull_commands.get(t, [])]
    lines += [f"  {c}" for c in cmds] or ["  (nothing to pull for this tier)"]
    if probe.notes:
        lines += ["", "Notes:", *[f"  - {n}" for n in probe.notes]]
    return "\n".join(lines) + "\n"


class ApplyError(Exception):
    """--apply refused (does not fit, or project.json unusable)."""


def apply_tier(
    config_path: Path, table: SuggestionTable, tier: Tier, *, force: bool = False
) -> dict[str, dict[str, str]]:
    """Rewrite `models` of project.json for `tier`; every other key is preserved."""
    from manuallabor.contracts.config import ProjectConfig
    from manuallabor.contracts.io import write_json

    if tier != "api" and not force:
        too_big = sorted(
            {r.task for r in table.rows if not getattr(r, tier).fits},
        )
        if too_big:
            raise ApplyError(
                f"tier {tier!r} does not fit this machine for: {', '.join(too_big)} "
                "(use --force to write it anyway)"
            )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("project.json is not an object")
    except (OSError, ValueError) as exc:
        raise ApplyError(f"cannot read {config_path}: {exc}") from exc
    chosen = tier_models(table, tier)
    models = raw.get("models")
    models = dict(models) if isinstance(models, dict) else {}
    for task, ref in chosen.items():
        models[task] = {"provider": ref["provider"], "model": ref["model"]}
    raw["models"] = models
    try:
        ProjectConfig.model_validate(raw)
    except ValueError as exc:
        raise ApplyError(f"resulting project.json would be invalid: {exc}") from exc
    write_json(config_path, raw)
    return chosen
