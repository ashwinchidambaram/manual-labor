"""T7: suggestion rules."""

from __future__ import annotations

from manuallabor.providers import probe as pr
from tests.providers import probe_support as ps


def test_m3_16gb_defaults_small() -> None:
    p = ps.mac_probe()
    t = pr.suggest(p)
    assert t.default_tier == "small"
    chat = next(r for r in t.rows if r.task == "cleanup")
    assert chat.small.fits and chat.small.speed_class == "fast"
    assert chat.medium.fits and chat.medium.speed_class == "ok"  # ~10.6 tok/s estimate
    assert not chat.large.fits and chat.large.speed_class == "n/a"
    vision = next(r for r in t.rows if r.task == "vision")
    assert not vision.large.fits and vision.medium.fits


def test_present_models_have_no_pull_command() -> None:
    t = pr.suggest(ps.mac_probe())
    cleanup = next(r for r in t.rows if r.task == "cleanup")
    emb = next(r for r in t.rows if r.task == "embeddings")
    assert cleanup.small.present and cleanup.small.pull_command is None
    assert emb.small.present  # nomic-embed-text:latest matches
    vision = next(r for r in t.rows if r.task == "vision")
    assert not vision.small.present and vision.small.pull_command == "ollama pull moondream"
    assert t.pull_commands["small"] == ["ollama pull moondream"]


def test_big_apple_max_picks_highest_fitting_tier() -> None:
    p = ps.mac_probe(ram_bytes=64 * 1024**3, brand="Apple M3 Max")
    t = pr.suggest(p)
    # By the written rules every large model fits in ~48 GB usable, so large is the default
    # (the design prose said medium; the rules are what is implemented).
    assert t.default_tier == "large"
    assert all(r.large.fits for r in t.rows)


def test_nvidia_24gb_fits_large_with_one_gb_headroom() -> None:
    p = ps.linux_probe({"nvidia-smi": ps.NVIDIA_ONE}, ram_kb=64 * 1024 * 1024)
    t = pr.suggest(p)
    chat = next(r for r in t.rows if r.task == "cleanup")
    assert chat.large.fits  # 9 + 1.5 <= 23.98 - 1
    vision = next(r for r in t.rows if r.task == "vision")
    assert vision.large.fits and vision.large.est_tokens_per_s == round(0.5 * 300 / 7.8, 1)


def test_cpu_only_8gb_nothing_beyond_small() -> None:
    p = ps.linux_probe({}, ram_kb=8 * 1024 * 1024)
    t = pr.suggest(p)
    assert t.default_tier == "small"
    for r in t.rows:
        assert r.medium.speed_class == "n/a" and r.large.speed_class == "n/a"
        assert not r.medium.fits and not r.large.fits


def test_disk_cap_forces_smaller_tier() -> None:
    big = ps.mac_probe(ram_bytes=64 * 1024**3, brand="Apple M3 Max", disk=200.0)
    assert pr.suggest(big).default_tier == "large"
    mid = ps.mac_probe(ram_bytes=64 * 1024**3, brand="Apple M3 Max", disk=20.0)
    assert pr.suggest(mid).default_tier == "medium"
    tiny = ps.mac_probe(ram_bytes=64 * 1024**3, brand="Apple M3 Max", disk=6.0)
    assert pr.suggest(tiny).default_tier == "small"


def test_api_column_always_present() -> None:
    t = pr.suggest(ps.mac_probe())
    for r in t.rows:
        assert r.api.fits and r.api.pull_command is None
        assert r.api.note and "data leaves the machine" in r.api.note
    emb = next(r for r in t.rows if r.task == "embeddings")
    assert emb.api.provider == "openai"  # Anthropic has no embeddings API
    assert next(r for r in t.rows if r.task == "cleanup").api.provider == "anthropic"


def test_deterministic_text() -> None:
    p = ps.mac_probe()
    a = pr.render_table(p, pr.suggest(p))
    b = pr.render_table(p, pr.suggest(p))
    assert a == b and "Commands to run yourself" in a and a.isascii()
    assert "ollama pull moondream" in a
