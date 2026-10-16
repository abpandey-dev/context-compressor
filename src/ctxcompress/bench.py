"""Benchmark plumbing: tasks, compressed contexts per method, and deterministic grading (no LLM judge)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import compress

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
METHODS = ["raw", "minify", "smart", "select", "smart+select", "llm_summary"]
LABELS = {"raw": "Raw", "minify": "Minify", "smart": "Smart (type-aware)", "select": "Select (BM25)",
          "smart+select": "Smart + select", "llm_summary": "LLM summary"}


def load_tasks() -> list[dict]:
    return [json.loads(ln) for ln in (DATA / "tasks.jsonl").read_text().splitlines() if ln.strip()]


def context(name: str) -> str:
    return (DATA / "contexts" / name).read_text()


def compressed(task: dict, method: str, summaries: dict | None = None) -> str:
    text = context(task["context"])
    if method == "llm_summary":
        return summaries[task["context"]]["text"]
    return compress(text, method, query=task["question"])


def _norm(s: str) -> str:
    s = re.sub(r"(\d)[tT ](\d)", r"\1\2", s)  # 2026-10-14T18:13 and 2026-10-14 18:13 are the same timestamp
    return re.sub(r"[^a-z0-9.:@+-]", "", s.lower())


def _numbers(s: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*(?:\.\d+)?", s)]


def grade(task: dict, answer: str | None) -> str:
    """'correct', 'wrong' or 'abstained' (said NOT_FOUND although the answer was in the original context)."""
    if answer is None:
        return "wrong"
    said_nf = "notfound" in _norm(answer).replace("_", "")
    if task["grade"] == "not_found":
        return "correct" if said_nf else "wrong"
    if said_nf:
        return "abstained"
    truth = task["answer"]
    if task["grade"] == "number":
        tol = max(abs(truth) * 1e-3, 1e-6)
        for x in _numbers(answer):
            for scale in (1, 1e6, 1e-6):  # "15.8 million" vs 15800000
                if abs(x * scale - truth) <= tol:
                    return "correct"
        return "wrong"
    return "correct" if _norm(str(truth)) in _norm(answer) else "wrong"
