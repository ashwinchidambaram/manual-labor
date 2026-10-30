"""Docling model discovery must accept the place `docling-tools models download` writes to.

The README tells people to run that command. Docling saves to `<docling cache_dir>/models`
(`~/.cache/docling/models` by default), not to the Hugging Face hub cache, so the parser must
look there too or the documented install step leaves the parser "unavailable". Under an
artifacts path docling never falls back to the hub cache, so only a complete folder counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuallabor.parse import pdf_docling

REPO_DIRS = [r.removeprefix("models--") for r in pdf_docling.MODEL_REPOS]


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("MANUALLABOR_DOCLING_ARTIFACTS", raising=False)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.setattr(pdf_docling, "docling_cache_dir", lambda: tmp_path / "docling")
    return tmp_path


def _hub_cache(root: Path) -> None:
    for repo in pdf_docling.MODEL_REPOS:
        (root / "hf" / repo).mkdir(parents=True)


def test_nothing_cached_means_not_cached(isolated: Path) -> None:
    assert pdf_docling.models_cached() is False
    assert pdf_docling.artifacts_path() is None


def test_docling_tools_download_location_counts_as_cached(isolated: Path) -> None:
    models = isolated / "docling" / "models"
    for name in REPO_DIRS:
        (models / name).mkdir(parents=True)
    assert pdf_docling.models_cached() is True
    assert pdf_docling.artifacts_path() == models


def test_hub_cache_still_counts_without_docling_dir(isolated: Path) -> None:
    _hub_cache(isolated)
    assert pdf_docling.models_cached() is True
    assert pdf_docling.artifacts_path() is None  # the converter resolves the hub cache itself


def test_empty_or_partial_docling_dir_does_not_hide_a_working_hub_cache(isolated: Path) -> None:
    _hub_cache(isolated)
    models = isolated / "docling" / "models"
    models.mkdir(parents=True)  # created by an interrupted download, or by an OCR model
    assert pdf_docling.artifacts_path() is None
    assert pdf_docling.models_cached() is True
    (models / REPO_DIRS[0]).mkdir()  # one of two repos
    assert pdf_docling.artifacts_path() is None
    assert pdf_docling.models_cached() is True


def test_partial_docling_dir_alone_is_not_cached(isolated: Path) -> None:
    (isolated / "docling" / "models" / REPO_DIRS[0]).mkdir(parents=True)
    assert pdf_docling.artifacts_path() is None
    assert pdf_docling.models_cached() is False


def test_explicit_artifacts_env_wins(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models = isolated / "docling" / "models"
    for name in REPO_DIRS:
        (models / name).mkdir(parents=True)
    explicit = isolated / "elsewhere"
    monkeypatch.setenv("MANUALLABOR_DOCLING_ARTIFACTS", str(explicit))
    assert pdf_docling.artifacts_path() == explicit
    assert pdf_docling.models_cached() is False  # the named directory does not exist
