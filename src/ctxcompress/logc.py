"""Log compression by pattern mining.

Every log entry (a timestamped line plus any continuation lines, e.g. a stack trace) is turned into a pattern by
masking the parts that vary: numbers, hex ids, UUIDs, IPs. A slot that only ever takes a few values (an HTTP
status, a version) is kept literal, so "200" and "503" stay separate patterns.

Rare patterns are kept verbatim, so one-off errors and deploys survive untouched. Repeated patterns become a
single line with a count, the first and last timestamp, and a summary of each varying slot (range and average for
numbers, the most common values when values repeat):

    [x1,204 09:00:03→10:59:58] INFO [checkout-api] GET /api/v1/cart/<1> 200 <2>ms user=u<3>
        <1>: 1,204 distinct | <2>: 8-480, avg 61 | <3>: most common 5531 x40, 1043 x12, 2210 x9
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

TS = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
                r"|[A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2})\s*")
VAR = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # uuid
                 r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"                                              # ipv4
                 r"|\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{6,}\b"                          # hex id
                 r"|\b[A-Za-z]{1,4}\d{2,}\b"                                                    # id like u4821
                 r"|\d+(?:\.\d+)?")                                                            # number
FEW = 4  # a slot with at most this many distinct values stays literal


def entries(text: str) -> list[tuple[str, str]]:
    """(timestamp, message) pairs; lines without a timestamp continue the previous entry."""
    out: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = TS.match(line)
        if m or not out:
            out.append([m.group(1) if m else "", line[m.end():] if m else line])
        else:
            out[-1][1] += "\n" + line
    return [(t, msg) for t, msg in out]


def _mask(msg: str) -> tuple[str, list[str]]:
    vals: list[str] = []

    def sub(m):
        vals.append(m.group(0))
        return "\x00"

    return VAR.sub(sub, msg), vals


def _fmt_num(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 or x == int(x) else f"{x:,.1f}"


def _slot_summary(vals: list[str], is_id: bool) -> str:
    """Measurements get a range and an average; identifiers get a distinct count and their most common values."""
    c = Counter(vals)
    nums = [float(v) for v in vals if re.fullmatch(r"\d+(?:\.\d+)?", v)]
    if not is_id and len(nums) == len(vals):
        return f"{_fmt_num(min(nums))}-{_fmt_num(max(nums))}, avg {_fmt_num(sum(nums) / len(nums))}"
    top = c.most_common(3)
    out = f"{len(c):,} distinct"
    if top[0][1] >= 3:
        return out + "; most common " + ", ".join(f"{v} x{n:,}" for v, n in top)
    return out + f", e.g. {', '.join(v for v, _ in top[:2])}"


def _is_id_slot(pattern_pieces: list[str], s: int) -> bool:
    """A slot is an identifier when it sits in a path (/cart/<id>), after a dash (SKU-<id>) or after req=/id=."""
    before = pattern_pieces[s]
    return bool(re.search(r"(/|-|#|\b(?:req|id|trace|span|user|order|sku)=)$", before, re.I))


def _short_ts(first: str, last: str) -> str:
    if first[:10] == last[:10] and len(last) > 11:
        return f"{first}→{last[11:]}"
    return f"{first}→{last}"


def compress(text: str, min_count: int = 5) -> str:
    es = entries(text)
    masked = [_mask(msg) for _, msg in es]
    # pass 1: group by masked pattern, find slots with few distinct values
    groups: dict[str, list[int]] = defaultdict(list)
    for i, (pat, _) in enumerate(masked):
        groups[pat].append(i)
    keys: list[tuple] = []
    for pat, idx in groups.items():
        n_slots = pat.count("\x00")
        literal = [len({masked[i][1][s] for i in idx}) <= FEW for s in range(n_slots)]
        for i in idx:
            vals = masked[i][1]
            keys.append((i, (pat, tuple(v if literal[s] else None for s, v in enumerate(vals)))))
    # pass 2: final groups
    final: dict[tuple, list[int]] = defaultdict(list)
    for i, k in sorted(keys):
        final[k].append(i)
    lines, emitted = [], set()
    first_of = {idx[0]: k for k, idx in final.items()}
    n_patterns = 0
    for i, (ts, msg) in enumerate(es):
        k = first_of.get(i)
        if k is None:
            if i in emitted:
                lines.append(_line(ts, msg))
            continue
        n_patterns += 1
        idx = final[k]
        if len(idx) < min_count:
            emitted.update(idx)
            lines.append(_line(ts, msg))
            continue
        pat, lits = k
        slots, out, n = [], [], 0
        for piece_i, piece in enumerate(pat.split("\x00")):
            out.append(piece)
            if piece_i < len(lits):
                if lits[piece_i] is not None:
                    out.append(lits[piece_i])
                else:
                    n += 1
                    out.append(f"<{n}>")
                    slots.append(piece_i)
        head = f"[x{len(idx):,} {_short_ts(es[idx[0]][0], es[idx[-1]][0])}] " if es[idx[0]][0] else f"[x{len(idx):,}] "
        lines.append(head + "".join(out))
        if slots:
            pieces = pat.split("\x00")
            summ = " | ".join(f"<{j + 1}>: {_slot_summary([masked[i][1][s] for i in idx], _is_id_slot(pieces, s))}"
                              for j, s in enumerate(slots))
            lines.append("    " + summ)
    header = (f"# {len(es):,} log entries -> {n_patterns:,} patterns. Patterns seen fewer than {min_count} times are "
              f"kept verbatim; repeated ones are summarised with a count, time range and slot values.")
    return header + "\n" + "\n".join(lines)


def _line(ts: str, msg: str) -> str:
    return f"{ts} {msg}" if ts else msg


def dedupe(text: str) -> str:
    """A lighter option: collapse runs of consecutive entries that differ only in their timestamp."""
    es = entries(text)
    out, i = [], 0
    while i < len(es):
        j = i
        while j + 1 < len(es) and es[j + 1][1] == es[i][1]:
            j += 1
        out.append(_line(es[i][0], es[i][1]) + (f"  [repeated x{j - i + 1} until {es[j][0]}]" if j > i else ""))
        i = j + 1
    return "\n".join(out)
