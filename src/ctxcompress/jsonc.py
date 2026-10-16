"""JSON compression.

`encode` turns any JSON value into a compact, indentation-based text that `decode` turns back into exactly the
same value (tested on every fixture plus random values). The savings come from four lossless moves:

  - no quotes, braces or commas around keys and simple strings
  - a list of objects becomes a table: the field names once, then one row per object
  - nested objects inside table rows are flattened into dotted columns (owner.login, owner.id, ...)
  - a field with the same value in every row is written once (`=same {...}`) instead of in every row

`prune` is the only lossy step, and it is optional: it drops null/empty fields and URL templates such as
"https://api.github.com/repos/x/y/issues{/number}".

Example:
    repos[2]{name,language,size}:
      =same {"private":false}
      agent-memory-engine,Python,42
      noc-copilot,Python,118
"""

from __future__ import annotations

import json
import re

_BARE_KEY = re.compile(r"^[A-Za-z_$@][\w$@-]*$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")
_URL_TEMPLATE = re.compile(r"\{[/?&+#]?[\w,]+\}")
MISSING = object()  # an empty table cell: this row has no such field


# ---------- scalars ----------

def _parse_scalar(tok: str):
    if tok == "null":
        return None
    if tok == "true":
        return True
    if tok == "false":
        return False
    if _NUMBER.match(tok):
        return float(tok) if any(c in tok for c in ".eE") else int(tok)
    return tok


def _fmt_scalar(v, in_row: bool) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, str):
        special = (not v or v != v.strip() or "\n" in v or v[0] in "\"{[=" or (in_row and "," in v)
                   or _parse_scalar(v) != v or type(_parse_scalar(v)) is not str)
        return json.dumps(v, ensure_ascii=False) if special else v
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # list/dict inside a cell


def _fmt_key(k: str) -> str:
    return k if _BARE_KEY.match(k) else json.dumps(k, ensure_ascii=False)


def _is_scalar(v) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


# ---------- tables ----------

def _flatten(row: dict, cols_nested: set[str], prefix: str = "") -> dict:
    out = {}
    for k, v in row.items():
        path = prefix + k
        if path in cols_nested:
            out.update(_flatten(v, cols_nested, path + "."))
        else:
            out[path] = v
    return out


def _nested_paths(rows: list[dict], prefix: str = "") -> set[str]:
    """Fields that are a non-empty object in every row (and whose keys are safe to join with dots)."""
    keys = {k for r in rows for k in r}
    paths = set()
    for k in keys:
        if not _BARE_KEY.match(k) or any(j.startswith(k + ".") for r in rows for j in r):
            continue
        vals = [r.get(k, MISSING) for r in rows]
        if all(isinstance(v, dict) and v and all(_BARE_KEY.match(j) for j in v) for v in vals):
            paths.add(prefix + k)
            paths |= _nested_paths(vals, prefix + k + ".")
    return paths


def _table(rows: list[dict], hoist: bool):
    nested = _nested_paths(rows)
    flat = [_flatten(r, nested) for r in rows]
    cols: list[str] = []
    for r in flat:
        for k in r:
            if k not in cols:
                cols.append(k)
    same = {}
    if hoist and len(flat) >= 3:
        for c in cols:
            vals = [r.get(c, MISSING) for r in flat]
            safe = "." not in c or c.rsplit(".", 1)[0] in nested  # never hoist a real key that contains a dot
            if safe and all(v is not MISSING for v in vals) and all(_same(v, vals[0]) for v in vals):
                same[c] = vals[0]
        cols = [c for c in cols if c not in same]
    paths = {c for c in cols if "." in c and c.rsplit(".", 1)[0] in nested}
    return cols, flat, same, paths


def _same(a, b) -> bool:
    return type(a) is type(b) and a == b


def _col_token(c: str, is_path: bool) -> str:
    # a flattened path is written bare with dots; any other key that isn't a plain name is quoted
    return c if is_path or _BARE_KEY.match(c) else json.dumps(c, ensure_ascii=False)


# ---------- encode ----------

def encode(value, hoist: bool = True) -> str:
    lines: list[str] = []
    _encode_into(lines, None, value, 0, hoist)
    return "\n".join(lines)


def _encode_into(lines, key, v, ind, hoist):
    pad = " " * ind
    head = "" if key is None else _fmt_key(key)
    if isinstance(v, dict):
        if not v:
            lines.append(f"{pad}{head}: {{}}" if key is not None else f"{pad}{{}}")
            return
        if key is not None:
            lines.append(f"{pad}{head}:")
            ind += 2
        for k, x in v.items():
            _encode_into(lines, k, x, ind, hoist)
        return
    if isinstance(v, list):
        if all(_is_scalar(x) for x in v):
            body = ",".join(_fmt_scalar(x, True) for x in v)
            lines.append(f"{pad}{head}[{len(v)}]:" + (f" {body}" if v else ""))
            return
        if len(v) >= 2 and all(isinstance(x, dict) for x in v):
            cols, flat, same, paths = _table(v, hoist)
            lines.append(f"{pad}{head}[{len(v)}]{{{','.join(_col_token(c, c in paths) for c in cols)}}}:")
            if same:
                lines.append(f"{pad}  =same " + json.dumps(same, ensure_ascii=False, separators=(",", ":")))
            for r in flat:
                cells = []
                for c in cols:
                    x = r.get(c, MISSING)
                    cells.append("" if x is MISSING else _fmt_scalar(x, True))
                lines.append(f"{pad}  " + ",".join(cells))
            return
        lines.append(f"{pad}{head}: " + json.dumps(v, ensure_ascii=False, separators=(",", ":")) if key is not None
                     else pad + json.dumps(v, ensure_ascii=False, separators=(",", ":")))
        return
    if key is None:  # a bare top-level value: always quote strings so it can't look like "key: value"
        lines.append(pad + (json.dumps(v, ensure_ascii=False) if isinstance(v, str) else _fmt_scalar(v, False)))
    else:
        lines.append(f"{pad}{head}: {_fmt_scalar(v, False)}")


# ---------- decode ----------

def _split_cells(s: str) -> list[str]:
    cells, i, n = [], 0, len(s)
    while True:
        start = i
        if i < n and s[i] == '"':
            i += 1
            while s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
        elif i < n and s[i] in "{[":
            depth, in_str = 0, False
            while i < n:
                ch = s[i]
                if in_str:
                    if ch == "\\":
                        i += 1
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch in "{[":
                    depth += 1
                elif ch in "}]":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        else:
            while i < n and s[i] != ",":
                i += 1
        cells.append(s[start:i])
        if i >= n:
            return cells
        i += 1  # skip the comma


def _cell(tok: str):
    if tok == "":
        return MISSING
    if tok[0] in '"{[':
        return json.loads(tok)
    return _parse_scalar(tok)


def _value(tok: str):
    if tok[0] in '"{[':
        return json.loads(tok)
    return _parse_scalar(tok)


def _read_key(line: str):
    """Split '<key>...' into (key, rest)."""
    if line.startswith('"'):
        end = _split_cells(line)[0]
        return json.loads(end), line[len(end):]
    m = re.match(r"[A-Za-z_$@][\w$@-]*", line)
    return m.group(0), line[m.end():]


_HEADER = re.compile(r"^\[(\d+)\](?:\{(.*)\})?:(?: (.*))?$")


def _unflatten(flat: dict, paths: list[str]) -> dict:
    out: dict = {}
    for c, v in flat.items():
        if v is MISSING:
            continue
        parts = c.split(".") if c in paths else [c]
        d = out
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = v
    return out


def decode(text: str):
    lines = text.split("\n")
    if lines[0].startswith("# compact JSON:"):
        lines = lines[1:]
    first = lines[0]
    if first.startswith("[") and _HEADER.match(first):
        val, _ = _decode_list(lines, 0, 0, first)
        return val
    if len(lines) == 1 and not _looks_like_kv(first):
        return _value(first)
    val, _ = _decode_dict(lines, 0, 0)
    return val


def _looks_like_kv(line: str) -> bool:
    try:
        _, rest = _read_key(line)
    except (AttributeError, ValueError, IndexError):
        return False
    return rest.startswith(":") or rest.startswith("[")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _decode_dict(lines, i, ind):
    out = {}
    while i < len(lines) and _indent(lines[i]) == ind:
        key, rest = _read_key(lines[i][ind:])
        if rest.startswith("["):
            out[key], i = _decode_list(lines, i, ind, rest)
        elif rest == ":":
            out[key], i = _decode_dict(lines, i + 1, ind + 2)
        else:
            out[key] = _value(rest[2:])
            i += 1
    return out, i


def _decode_list(lines, i, ind, header):
    m = _HEADER.match(header)
    n, cols_s, body = int(m.group(1)), m.group(2), m.group(3)
    if cols_s is None:
        vals = [] if not body else [_cell(c) for c in _split_cells(body)]
        assert len(vals) == n, f"expected {n} values"
        return vals, i + 1
    cols_tok = _split_cells(cols_s) if cols_s else []
    cols = [json.loads(c) if c.startswith('"') else c for c in cols_tok]
    paths = [c for c, t in zip(cols, cols_tok) if not t.startswith('"') and "." in c]
    i += 1
    same = {}
    if i < len(lines) and lines[i][ind + 2:].startswith("=same "):
        same = json.loads(lines[i][ind + 2 + 6:])
        paths += [c for c in same if "." in c]  # only flattened paths are ever hoisted with a dot
        i += 1
    rows = []
    for _ in range(n):
        cells = [_cell(c) for c in _split_cells(lines[i][ind + 2:])] if cols else []
        flat = dict(zip(cols, cells))
        flat.update(same)
        rows.append(_unflatten(flat, paths))
        i += 1
    return rows, i


# ---------- lossy pruning ----------

def _is_blob(s: str) -> bool:
    """Signatures, base64 payloads and other long opaque strings an LLM can't use."""
    if len(s) < 200:
        return False
    if s.startswith("-----BEGIN"):
        return True
    body = s.replace("\n", "")
    return " " not in body and sum(c.isalnum() or c in "+/=_-" for c in body) / len(body) > 0.97


def prune(v, drop_url_templates: bool = True):
    """Drop null / empty fields, URL templates and opaque blobs (signatures, base64). The only lossy JSON step."""
    if isinstance(v, str) and _is_blob(v):
        return f"<{len(v):,}-char blob omitted>"
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            x = prune(x, drop_url_templates)
            if x is None or x == "" or x == [] or x == {}:
                continue
            if drop_url_templates and isinstance(x, str) and x.startswith("http") and _URL_TEMPLATE.search(x):
                continue
            out[k] = x
        return out
    if isinstance(v, list):
        return [prune(x, drop_url_templates) for x in v]
    return v


def minify(text: str) -> str:
    return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))


LEGEND = ("# compact JSON: `name[N]{a,b}:` is a table of N items, one row each, columns a,b (dots = nested "
          "fields); `=same {...}` = fields identical in every row; empty cell = field absent")


def compress(text: str, lossy: bool = True, legend: bool = True) -> str:
    v = json.loads(text)
    body = encode(prune(v) if lossy else v)
    return (LEGEND + "\n" + body) if legend and "]{" in body else body
