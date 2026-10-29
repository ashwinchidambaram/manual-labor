"""T6: pure probe parsers and detectors with canned output."""

from __future__ import annotations

import pytest

from manuallabor.contracts.probe import ProbeResult
from manuallabor.providers import probe as pr
from tests.providers import probe_support as ps


def test_parse_sysctl_macos() -> None:
    s = pr.parse_sysctl_macos("Apple M3\n", "17179869184\n", "8\n", "8\n")
    assert (s.cpu_model, s.ram_bytes, s.cores_physical, s.cores_logical) == (
        "Apple M3",
        17179869184,
        8,
        8,
    )
    g = pr.parse_sysctl_macos(None, "garbage", "", None)
    assert (g.cpu_model, g.ram_bytes, g.cores_physical) == (None, None, None)


def test_parse_system_profiler() -> None:
    assert pr.parse_system_profiler(ps.SYSTEM_PROFILER) == ("Apple M3", 10)
    assert pr.parse_system_profiler("not json") == (None, None)
    assert pr.parse_system_profiler('{"SPDisplaysDataType": []}') == (None, None)
    assert pr.parse_system_profiler(None) == (None, None)


def test_parse_nvidia_smi() -> None:
    one = pr.parse_nvidia_smi_csv(ps.NVIDIA_ONE)
    assert one == [("NVIDIA GeForce RTX 4090", pytest.approx(24564 / 1024))]
    two = pr.parse_nvidia_smi_csv(ps.NVIDIA_TWO)
    assert len(two) == 2 and two[1][1] == pytest.approx(40.0)
    assert pr.parse_nvidia_smi_csv("") == []
    assert pr.parse_nvidia_smi_csv("No devices were found") == []
    assert pr.parse_nvidia_smi_csv("name, notanumber") == []


def test_parse_rocm_smi() -> None:
    cards = pr.parse_rocm_smi_json(ps.ROCM)
    assert [c[0] for c in cards] == ["Radeon RX 7900 XTX", "Radeon RX 6600"]
    assert cards[0][1] == pytest.approx(25753026560 / 1024**3)
    assert pr.parse_rocm_smi_json("nope") == []
    assert pr.parse_rocm_smi_json("[]") == []


def test_parse_meminfo_cpuinfo() -> None:
    assert pr.parse_meminfo(ps.MEMINFO) == pytest.approx(16384000 * 1024 / 1024**3)
    assert pr.parse_meminfo("garbage") is None
    assert pr.parse_cpuinfo(ps.CPUINFO) == ("AMD Ryzen 7 5800X", 2)
    assert pr.parse_cpuinfo("") == (None, None)


def test_parse_ollama_tags() -> None:
    models = pr.parse_ollama_tags(ps.TAGS)
    assert [m.name for m in models] == ["llama3.2:1b", "nomic-embed-text:latest"]
    assert models[0].size_gb == pytest.approx(1.2, abs=0.1) and models[0].digest == "baf6a787fdff"
    assert pr.parse_ollama_tags("{}") == [] and pr.parse_ollama_tags("") == []


def test_mac_detection_end_to_end() -> None:
    p = ps.mac_probe()
    assert p.ram_gb == 16.0 and p.cpu.model == "Apple M3"
    assert p.gpu is not None and p.gpu.vendor == "apple" and p.gpu.unified
    assert p.effective_model_memory_gb == pytest.approx(10.6, abs=0.05)
    assert p.ollama.reachable and p.ollama.version == "0.40.2"
    assert ProbeResult.model_validate_json(p.model_dump_json()) == p


def test_big_mac_uses_75_percent() -> None:
    p = ps.mac_probe(ram_bytes=64 * 1024**3, brand="Apple M3 Max")
    assert p.effective_model_memory_gb == pytest.approx(48.0)


def test_linux_nvidia_and_amd_and_cpu_only() -> None:
    nv = ps.linux_probe({"nvidia-smi": ps.NVIDIA_ONE})
    assert nv.gpu is not None and nv.gpu.vendor == "nvidia"
    assert nv.effective_model_memory_gb == pytest.approx(24564 / 1024, abs=0.05)
    amd = ps.linux_probe({"rocm-smi": ps.ROCM})
    assert amd.gpu is not None and amd.gpu.vendor == "amd" and amd.gpu.name == "Radeon RX 7900 XTX"
    cpu = ps.linux_probe({})
    assert cpu.gpu is None and cpu.effective_model_memory_gb == pytest.approx(
        cpu.ram_gb * 0.5, abs=0.1
    )
    assert any("CPU-only" in n for n in cpu.notes)
    assert cpu.cpu.model == "AMD Ryzen 7 5800X"


def test_failures_become_notes_never_exceptions() -> None:
    runner = ps.RecordingRunner({})  # every command returns None (missing/timeout/non-zero)
    p = pr.run_probe(
        runner=runner,
        clock=lambda: ps.FIXED,
        system="Darwin",
        machine="arm64",
        env={},
        http_get=lambda u, t: None,
        which=lambda n: None,
        disk_free=lambda p: 1.0,
    )
    assert p.ram_gb == 0.0 and p.notes
    assert not p.ollama.installed and not p.ollama.reachable
    other = pr.run_probe(
        runner=runner,
        clock=lambda: ps.FIXED,
        system="Plan9",
        machine="x",
        env={},
        http_get=lambda u, t: None,
        which=lambda n: None,
        disk_free=lambda p: 1.0,
    )
    assert any("unsupported platform" in n for n in other.notes)


def test_default_runner_handles_missing_binary_and_timeout() -> None:
    assert pr.default_runner(["definitely-not-a-binary-xyz"], 1.0) is None
    assert pr.default_runner(["sleep", "5"], 0.2) is None
    assert pr.default_runner(["false"], 1.0) is None
