"""ctxcompress: shrink tool outputs, logs and documents before they reach an LLM.

    from ctxcompress import compress
    small = compress(tool_output)                                  # type-aware, query-agnostic
    tiny = compress(tool_output, "smart+select", query=question)   # plus query-aware selection

Methods:
    raw           unchanged
    minify        whitespace only (compact JSON, collapsed spaces)
    smart         type-aware: JSON -> lossless tables (+ null pruning), logs -> patterns, text -> cleanup
    select        query-aware BM25 selection over the raw units (records, log entries, text chunks)
    smart+select  smart, then query-aware selection over its units
"""

from __future__ import annotations

import json
import re

from . import jsonc, logc, textc
from .select import select

__all__ = ["compress", "detect", "METHODS"]
METHODS = ["raw", "minify", "smart", "select", "smart+select"]
_ROW_HEADER = re.compile(r"^( *)(?:\S.*)?\[\d+\]\{.*\}:$")


def detect(text: str) -> str:
    s = text.lstrip()
    if s[:1] in "[{":
        try:
            json.loads(text)
            return "json"
        except ValueError:
            pass
    lines = [ln for ln in text.splitlines() if ln.strip()][:200]
    if lines and sum(bool(logc.TS.match(ln)) for ln in lines) >= 0.5 * len(lines):
        return "log"
    return "text"


def _minify(text: str, kind: str) -> str:
    if kind == "json":
        return jsonc.minify(text)
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines() if ln.strip())


def _smart(text: str, kind: str) -> str:
    if kind == "json":
        return jsonc.compress(text)
    if kind == "log":
        return logc.compress(text)
    return textc.clean(text)


def _raw_units(text: str, kind: str) -> tuple[list[str], set[int]]:
    if kind == "json":
        v = json.loads(text)
        if isinstance(v, dict):
            lists = {k: x for k, x in v.items() if isinstance(x, list) and len(x) > 1}
            if lists:
                k = max(lists, key=lambda k: len(json.dumps(lists[k])))
                rest = {a: b for a, b in v.items() if a != k}
                head = json.dumps(rest, ensure_ascii=False, separators=(",", ":")) + f'\n"{k}":'
                return [head] + [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in v[k]], {0}
            return [jsonc.minify(text)], {0}
        if isinstance(v, list):
            return [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in v], set()
        return [text], {0}
    if kind == "log":
        return [logc._line(t, m) for t, m in logc.entries(text)], set()
    return textc.chunks(text), set()


def _smart_units(small: str, kind: str) -> tuple[list[str], set[int]]:
    lines = small.split("\n")
    if kind == "json":  # table rows are units; every other line (headers, =same, key: value) is always kept
        keep, row_indent = set(), None
        for i, ln in enumerate(lines):
            ind = len(ln) - len(ln.lstrip(" "))
            if row_indent is not None and ind == row_indent:
                if ln.lstrip().startswith("=same "):
                    keep.add(i)
                continue
            row_indent = None
            keep.add(i)
            m = _ROW_HEADER.match(ln)
            if m:
                row_indent = len(m.group(1)) + 2
        return lines, keep
    if kind == "log":  # a pattern line and its slot summary travel together
        units: list[str] = []
        for ln in lines:
            if ln.startswith("    ") and units:
                units[-1] += "\n" + ln
            else:
                units.append(ln)
        return units, {0}
    return textc.chunks(small), set()


def compress(text: str, method: str = "smart", query: str | None = None, budget: float | None = None,
             kind: str | None = None) -> str:
    kind = kind or detect(text)
    if method == "raw":
        return text
    if method == "minify":
        return _minify(text, kind)
    if method == "smart":
        return _smart(text, kind)
    if not query:
        raise ValueError(f"{method} needs a query")
    if method == "select":
        units, keep = _raw_units(text, kind)
        return select(units, query, int(len(_minify(text, kind)) * (budget or 0.2)), keep)
    if method == "smart+select":
        small = _smart(text, kind)
        units, keep = _smart_units(small, kind)
        return select(units, query, int(len(small) * (budget or 0.5)), keep)
    raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
