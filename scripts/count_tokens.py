"""Exact prompt sizes (Claude's own tokenizer, via the free count_tokens endpoint) for every task x method.

Writes results/tokens.csv. The LLM-summary method is counted by run_eval.py, after the summaries exist.
"""

from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxcompress import bench, llm  # noqa: E402

METHODS = [m for m in bench.METHODS if m != "llm_summary"]


def main():
    c = llm.client()
    tasks = bench.load_tasks()
    jobs = [(t, m) for t in tasks for m in METHODS]

    def one(job):
        t, m = job
        ctx = bench.compressed(t, m)
        n = llm.count_tokens(c, llm.prompt(ctx, t["question"]), system=llm.SYSTEM)
        return {"task": t["id"], "context": t["context"], "method": m, "tokens": n, "chars": len(ctx)}

    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(one, jobs))
    out = ROOT / "results" / "tokens.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} counts in {time.time() - t0:.0f}s -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
