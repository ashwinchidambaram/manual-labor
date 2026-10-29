"""Deterministic clustering of centered embeddings (design §3.3). No random seeds."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from manuallabor import ids
from manuallabor.contracts.group import GroupingParams

EPS = 1e-12


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1)
    small = norms < EPS
    out = m / np.where(small, 1.0, norms)[:, None]
    if small.any():
        out[small] = 0.0
        out[small, 0] = 1.0
    return np.asarray(out, dtype=np.float64)


def center(v: np.ndarray) -> np.ndarray:
    """Subtract the document mean and re-normalize rows. Anisotropic embedding models put
    every pair at 0.8-0.9 raw cosine; centering makes one threshold work across models."""
    if v.shape[0] == 0:
        return v.astype(np.float64)
    return _normalize(v - v.mean(axis=0))


def centroid(c: np.ndarray, idx: Sequence[int]) -> np.ndarray:
    m = c[list(idx)].mean(axis=0)
    n = float(np.linalg.norm(m))
    if n < EPS:
        return np.asarray(c[idx[0]], dtype=np.float64)
    return np.asarray(m / n, dtype=np.float64)


def cohesion(c: np.ndarray, idx: Sequence[int]) -> float:
    """Mean pairwise cosine of the members' centered rows, clamped to [0,1], rounded to 6."""
    m = len(idx)
    if m < 2:
        return 0.0
    s = c[list(idx)].sum(axis=0)
    val = (float(s @ s) - m) / (m * (m - 1))
    return round(min(1.0, max(0.0, val)), 6) + 0.0


def _split_tree(
    z: np.ndarray,
    n: int,
    labels: np.ndarray,
    max_size: int,
    cannot: Sequence[tuple[int, int]],
) -> list[list[int]]:
    """Top-down walk of the dendrogram: a node whose leaves share one cut label is a cluster;
    it is split into its two children while it is too big or holds both ends of a cannot-link
    pair."""
    total = 2 * n - 1
    lo = np.zeros(total, dtype=np.int64)
    hi = np.zeros(total, dtype=np.int64)
    lo[:n] = labels
    hi[:n] = labels
    size = np.ones(total, dtype=np.int64)
    parent = np.full(total, -1, dtype=np.int64)
    for i in range(n - 1):
        a, b = int(z[i, 0]), int(z[i, 1])
        node = n + i
        lo[node] = min(lo[a], lo[b])
        hi[node] = max(hi[a], hi[b])
        size[node] = size[a] + size[b]
        parent[a] = parent[b] = node
    violating = np.zeros(total, dtype=bool)
    if cannot:
        # lowest common ancestor of a pair = first merge that joins their components
        uf = list(range(total))

        def find(x: int) -> int:
            while uf[x] != x:
                uf[x] = uf[uf[x]]
                x = uf[x]
            return x

        pending = list(cannot)
        for i in range(n - 1):
            a, b = int(z[i, 0]), int(z[i, 1])
            node = n + i
            uf[find(a)] = node
            uf[find(b)] = node
            still: list[tuple[int, int]] = []
            for p, q in pending:
                if find(p) == find(q):
                    x = node
                    while x != -1 and not violating[x]:
                        violating[x] = True
                        x = int(parent[x])
                else:
                    still.append((p, q))
            pending = still
    out: list[list[int]] = []
    stack = [total - 1]
    while stack:
        node = stack.pop()
        if node < n:
            out.append([node])
            continue
        i = node - n
        single = lo[node] == hi[node]
        if single and size[node] <= max_size and not violating[node]:
            leaves: list[int] = []
            work = [node]
            while work:
                x = work.pop()
                if x < n:
                    leaves.append(x)
                else:
                    work.append(int(z[x - n, 0]))
                    work.append(int(z[x - n, 1]))
            out.append(sorted(leaves))
        else:
            stack.append(int(z[i, 0]))
            stack.append(int(z[i, 1]))
    return out


def cluster(
    c: np.ndarray,
    block_ids: Sequence[str],
    params: GroupingParams,
    cannot_link: Sequence[tuple[str, str]] = (),
) -> list[list[int]]:
    """Clusters of row indexes of `c` (each sorted, the list sorted by first member in block id
    order). Rows not in any returned cluster are stragglers."""
    n = c.shape[0]
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: ids.block_sort_key(block_ids[i]))
    cs = c[order]
    pos = {block_ids[i]: k for k, i in enumerate(order)}
    clusters: list[list[int]]
    if n < max(params.small_doc, 3):
        clusters = [list(range(n))]
    else:
        y = np.round(pdist(cs, "cosine"), 9)
        y = np.clip(y, 0.0, 2.0) + 0.0
        z = linkage(y, method="average")
        labels = fcluster(z, params.d_cut, "distance")
        k_max = max(1, n // params.k_max_divisor)
        if int(labels.max()) > k_max:
            labels = fcluster(z, k_max, "maxclust")
        cl_pairs = [(pos[a], pos[b]) for a, b in cannot_link if a in pos and b in pos and a != b]
        clusters = _split_tree(z, n, labels, params.max_topic_blocks, cl_pairs)
    kept = [sorted(m) for m in clusters if len(m) >= params.min_topic_blocks]
    if not kept:
        kept = [list(range(n))]
    kept.sort(key=lambda m: m[0])
    return [sorted(order[i] for i in m) for m in kept]
