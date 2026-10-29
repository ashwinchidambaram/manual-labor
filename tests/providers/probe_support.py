"""Canned hardware outputs and probe builders for the probe tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from manuallabor.contracts.probe import ProbeResult
from manuallabor.providers.probe import run_probe

M3_SYSCTL = {
    "machdep.cpu.brand_string": "Apple M3\n",
    "hw.memsize": "17179869184\n",
    "hw.physicalcpu": "8\n",
    "hw.logicalcpu": "8\n",
}
SYSTEM_PROFILER = json.dumps(
    {
        "SPDisplaysDataType": [
            {
                "_name": "Apple M3",
                "sppci_cores": "10",
                "sppci_model": "Apple M3",
                "sppci_vendor": "sppci_vendor_Apple",
            }
        ]
    }
)
TAGS = json.dumps(
    {
        "models": [
            {"name": "llama3.2:1b", "size": 1321098329, "digest": "baf6a787fdff" + "0" * 52},
            {
                "name": "nomic-embed-text:latest",
                "size": 274302450,
                "digest": "0a109f422b47" + "0" * 52,
            },
        ]
    }
)
NVIDIA_ONE = "NVIDIA GeForce RTX 4090, 24564\n"
NVIDIA_TWO = "NVIDIA A100-SXM4-40GB, 40960\nNVIDIA A100-SXM4-40GB, 40960\n"
ROCM = json.dumps(
    {
        "card0": {"Card Series": "Radeon RX 7900 XTX", "VRAM Total Memory (B)": "25753026560"},
        "card1": {"Card Series": "Radeon RX 6600", "VRAM Total Memory (B)": "8573157376"},
        "system": {"Driver version": "6.7.0"},
    }
)
MEMINFO = "MemTotal:       16384000 kB\nMemFree:         1234 kB\n"
CPUINFO = (
    "processor\t: 0\nmodel name\t: AMD Ryzen 7 5800X\n\n"
    "processor\t: 1\nmodel name\t: AMD Ryzen 7 5800X\n"
)
FIXED = datetime(2026, 1, 1, tzinfo=UTC)


class RecordingRunner:
    def __init__(self, outputs: dict[str, str | None] | None = None) -> None:
        self.outputs = outputs if outputs is not None else dict(M3_SYSCTL)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str], timeout: float = 3.0) -> str | None:
        self.calls.append(list(cmd))
        if cmd[:2] == ["sysctl", "-n"]:
            return self.outputs.get(cmd[2])
        if cmd[0] == "system_profiler":
            return self.outputs.get("system_profiler", SYSTEM_PROFILER)
        if cmd[0] == "ollama":
            return self.outputs.get("ollama", "ollama version is 0.40.2\n")
        if cmd[0] in ("nvidia-smi", "rocm-smi"):
            return self.outputs.get(cmd[0])
        return None


def mac_probe(
    ram_bytes: int = 17179869184, brand: str = "Apple M3", disk: float = 50.0
) -> ProbeResult:
    out = {**M3_SYSCTL, "hw.memsize": f"{ram_bytes}\n", "machdep.cpu.brand_string": f"{brand}\n"}
    sp = json.dumps({"SPDisplaysDataType": [{"sppci_model": brand, "sppci_cores": "10"}]})
    runner = RecordingRunner({**out, "system_profiler": sp})
    return run_probe(
        runner=runner,
        clock=lambda: FIXED,
        path=Path("/tmp"),
        system="Darwin",
        machine="arm64",
        env={},
        http_get=lambda url, t: TAGS,
        which=lambda n: "/usr/local/bin/ollama",
        disk_free=lambda p: disk,
    )


def linux_probe(
    smi: dict[str, str | None], ram_kb: int = 33554432, disk: float = 200.0
) -> ProbeResult:
    files = {
        "/proc/meminfo": f"MemTotal:       {ram_kb} kB\n",
        "/proc/cpuinfo": CPUINFO,
    }
    return run_probe(
        runner=RecordingRunner(smi),
        clock=lambda: FIXED,
        path=Path("/tmp"),
        system="Linux",
        machine="x86_64",
        env={},
        http_get=lambda url, t: None,
        read_text=lambda p: files.get(p),
        which=lambda n: None,
        disk_free=lambda p: disk,
    )
