"""Ask Claude every question with every compression method and grade the answers.

    python scripts/run_eval.py                                   # Claude Haiku 5.5, all methods
    python scripts/run_eval.py --model claude-sonnet-5-5 --methods raw smart

Each answer is cached in results/<model>/<method>/<task>.json, so a rerun only pays for what's missing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxcompress import bench, llm  # noqa: E402


def summaries(c, model: str, contexts: list[str]) -> dict:
    """The LLM-summary baseline: one query-agnostic summary per context, made once and reused."""
    out = {}
    for name in contexts:
        f = ROOT / "results" / model / "llm_summary" / "_summaries" / f"{name}.json"
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            s = llm.summarize(c, bench.context(name), model=model)
            f.write_text(json.dumps(s, ensure_ascii=False, indent=1))
            print(f"  summary {name}: {s['input_tokens']:,} -> {s['output_tokens']:,} tokens, ${s['cost']:.4f}")
        out[name] = json.loads(f.read_text())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=llm.MODEL)
    ap.add_argument("--methods", nargs="+", default=bench.METHODS)
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    c = llm.client()
    tasks = bench.load_tasks()
    summ = summaries(c, args.model, sorted({t["context"] for t in tasks})) if "llm_summary" in args.methods else {}

    def one(job):
        t, m = job
        f = ROOT / "results" / args.model / m / f"{t['id']}.json"
        if f.exists():
            return json.loads(f.read_text())
        ctx = bench.compressed(t, m, summ)
        r = llm.answer(c, ctx, t["question"], model=args.model, effort=args.effort)
        r.update(task=t["id"], context=t["context"], category=t["category"], method=m, model=args.model,
                 truth=t["answer"], verdict=bench.grade(t, r["answer"]))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1))
        return r

    jobs = [(t, m) for m in args.methods for t in tasks]
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        rows = list(ex.map(one, jobs))
    spent = sum(r["cost"] for r in rows) + sum(s["cost"] for s in summ.values())
    print(f"{len(rows)} answers in {time.time() - t0:.0f}s; cost of these results ${spent:.4f}")
    for m in args.methods:
        rs = [r for r in rows if r["method"] == m]
        ok = sum(r["verdict"] == "correct" for r in rs)
        print(f"  {m:13s} {ok}/{len(rs)} correct, {sum(r['input_tokens'] for r in rs) / len(rs):,.0f} input tokens "
              f"per question")


if __name__ == "__main__":
    main()
