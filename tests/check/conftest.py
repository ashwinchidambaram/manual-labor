"""Remove each test's temp directory when it ends (the shared basetemp has a 2 GiB guard)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _drop_tmp_path(tmp_path: Path) -> Iterator[None]:
    yield
    shutil.rmtree(tmp_path, ignore_errors=True)
