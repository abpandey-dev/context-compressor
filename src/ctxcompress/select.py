"""Query-aware selection: keep only the parts of a context that look relevant to the question (BM25).

This is retrieval, RAG-style: very small outputs, but anything that needs the whole context (a count, a total,
"which is the largest") can be lost. The benchmark measures exactly that trade-off.
"""

from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an and are as at be by did do does for from had has have how i in is it its many much of on or the
this to was were what when where which who whom why with""".split())


def tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", s.lower()) if t not in STOP]


def bm25(units: list[str], query: str, k1: float = 1.2, b: float = 0.75) -> list[float]:
    docs = [Counter(tokens(u)) for u in units]
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / max(n, 1) or 1
    df = Counter(t for d in docs for t in d)
    q = set(tokens(query))
    scores = []
    for d in docs:
        dl = sum(d.values())
        s = 0.0
        for t in q:
            if t in d:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * dl / avg))
        scores.append(s)
    return scores


def select(units: list[str], query: str, budget_chars: int, keep: set[int] | None = None, sep: str = "\n") -> str:
    """Keep the best-scoring units (plus `keep`, e.g. table headers) within the budget, in their original order."""
    keep = set(keep or ())
    used = sum(len(units[i]) + 1 for i in keep)
    scores = bm25(units, query)
    for i in sorted(range(len(units)), key=lambda i: -scores[i]):
        if i in keep or scores[i] <= 0:
            continue
        if used + len(units[i]) + 1 > budget_chars and len(keep) > 0:
            continue
        keep.add(i)
        used += len(units[i]) + 1
    out, gap = [], 0
    for i, u in enumerate(units):
        if i in keep:
            if gap:
                out.append(f"[... {gap} omitted ...]")
                gap = 0
            out.append(u)
        else:
            gap += 1
    if gap:
        out.append(f"[... {gap} omitted ...]")
    return sep.join(out)
