"""Embedding of block summaries through the provider layer (design §3.2)."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from manuallabor.contracts.enums import Task
from manuallabor.grouping.types import TopicFailure
from manuallabor.providers.base import Provider, ProviderError


def embed_blocks(
    provider: Provider,
    ids: Sequence[str],
    texts: Sequence[str],
    *,
    prefix: str,
    batch: int,
) -> np.ndarray:
    """L2-normalized float64 matrix with one row per text, in the given (block id) order.

    Any provider failure or malformed vector raises TopicFailure: there is no fallback to
    another model."""
    if len(ids) != len(texts):
        raise ValueError("ids and texts must have the same length")
    rows: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = [prefix + t for t in texts[i : i + batch]]
        try:
            vecs = provider.embed(Task.embeddings, chunk)
        except ProviderError as exc:
            raise TopicFailure(f"embedding failed: {exc}") from exc
        if len(vecs) != len(chunk):
            raise TopicFailure(f"embedding returned {len(vecs)} vectors for {len(chunk)} texts")
        rows.extend(vecs)
    if not rows:
        return np.zeros((0, 0), dtype=np.float64)
    dim = len(rows[0])
    for r in rows:
        if len(r) != dim or dim == 0:
            raise TopicFailure("embedding vectors have unequal or zero dimension")
        if any(not math.isfinite(x) for x in r):
            raise TopicFailure("embedding vector has a non-finite value")
    v = np.asarray(rows, dtype=np.float64)
    norms = np.linalg.norm(v, axis=1)
    if not np.all(norms > 0):
        raise TopicFailure("embedding vector has zero norm")
    return np.asarray(v / norms[:, None], dtype=np.float64)
