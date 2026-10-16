"""Plain-text / document cleanup: whitespace, page furniture and repeated boilerplate lines."""

from __future__ import annotations

import re
from collections import Counter


def clean(text: str, repeat: int = 3, min_len: int = 20) -> str:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    counts = Counter(ln for ln in lines if len(ln) >= min_len)
    out, seen, blank = [], set(), False
    for ln in lines:
        if re.fullmatch(r"\d{1,3}|[-_=.•·\s]{3,}|Page \d+( of \d+)?", ln):  # page numbers, rules
            continue
        if counts.get(ln, 0) >= repeat:  # running headers and footers: keep the first copy only
            if ln in seen:
                continue
            seen.add(ln)
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
            continue
        blank = False
        out.append(ln)
    return "\n".join(out).strip()


def chunks(text: str, size: int = 400) -> list[str]:
    """Split on blank lines, then pack lines into chunks of about `size` characters."""
    out, cur = [], []
    for ln in text.splitlines():
        if not ln.strip():
            if cur:
                out.append("\n".join(cur))
                cur = []
            continue
        cur.append(ln)
        if sum(len(x) + 1 for x in cur) >= size:
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return out
