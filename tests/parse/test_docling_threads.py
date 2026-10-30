"""Docling's torch thread count is a fixed 4 on every machine (design 01 section 4.2, invariant 7).

A count derived from the machine's cores ran the reference configuration only on 5+ cores; torch
reductions are not guaranteed bit-identical across thread counts, so block IDs could differ
between a laptop and a 2-vCPU runner. The API is protected by the worker's nice level instead."""

from __future__ import annotations

import inspect

import manuallabor.parse.pdf_docling as pdf_docling
from manuallabor.jobs.runner import WORKER_NICE


def test_docling_threads_are_a_fixed_four() -> None:
    assert pdf_docling.NUM_THREADS == 4
    assert "cpu_count" not in inspect.getsource(pdf_docling)


def test_the_worker_runs_below_the_api() -> None:
    assert WORKER_NICE > 0
