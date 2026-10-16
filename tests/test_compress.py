import json
import random
import string
from pathlib import Path

import pytest

from ctxcompress import bench, compress, detect, jsonc, logc
from ctxcompress.select import select

CTX = Path(__file__).resolve().parents[1] / "data" / "contexts"
JSON_FIXTURES = sorted(CTX.glob("*.json"))


# ---------- JSON: lossless encoding ----------

@pytest.mark.parametrize("path", JSON_FIXTURES, ids=lambda p: p.name)
def test_roundtrip_on_real_api_responses(path):
    v = json.loads(path.read_text())
    assert jsonc.decode(jsonc.encode(v)) == v
    p = jsonc.prune(v)
    assert jsonc.decode(jsonc.compress(path.read_text())) == p  # the legend line is skipped too


def _rand_value(rnd, depth=0):
    kind = rnd.choice(["str", "int", "float", "bool", "none", "list", "dict", "rows"] if depth < 3 else ["str", "int"])
    if kind == "str":
        pool = ["", " x", "a,b", "null", "true", "12", "007", "-3", "1e5", '"q"', "=same", "[x]", "{y}", "line\nbreak",
                "a: b", "ok", "#tag", "-", "x.y", "名前"]
        return rnd.choice(pool + ["".join(rnd.choice(string.ascii_letters + ",: .") for _ in range(rnd.randint(1, 8)))])
    if kind == "int":
        return rnd.randint(-10**12, 10**12)
    if kind == "float":
        return rnd.choice([0.5, -2.25, 1e-7, 3.0, 52610000.0])
    if kind == "bool":
        return rnd.choice([True, False])
    if kind == "none":
        return None
    if kind == "list":
        return [_rand_value(rnd, depth + 1) for _ in range(rnd.randint(0, 4))]
    keys = ["id", "name", "a.b", "with space", "x", "owner", "$ref", "@t", "k-1", ""]
    if kind == "dict":
        return {rnd.choice(keys): _rand_value(rnd, depth + 1) for _ in range(rnd.randint(0, 4))}
    shared = {"owner": {"login": "me", "id": 1}, "private": False}
    return [dict(shared, **{rnd.choice(keys): _rand_value(rnd, depth + 1) for _ in range(rnd.randint(0, 3))})
            for _ in range(rnd.randint(2, 5))]


def test_roundtrip_on_random_values():
    rnd = random.Random(0)
    for _ in range(3000):
        v = _rand_value(rnd)
        assert jsonc.decode(jsonc.encode(v)) == v, v


def test_table_hoists_and_flattens():
    rows = [{"name": n, "size": s, "owner": {"login": "me"}, "private": False} for n, s in [("a", 1), ("b", 2), ("c", 3)]]
    out = jsonc.encode({"repos": rows})
    assert out.splitlines()[0] == "repos[3]{name,size}:"
    assert '=same {"owner.login":"me","private":false}' in out
    assert "  a,1" in out and jsonc.decode(out) == {"repos": rows}


def test_strings_that_look_like_other_types_are_quoted():
    v = [{"v": "12"}, {"v": "true"}, {"v": "a,b"}, {"v": ""}]
    out = jsonc.encode(v)
    assert '"12"' in out and '"true"' in out and '"a,b"' in out and '""' in out
    assert jsonc.decode(out) == v


def test_prune_drops_empties_url_templates_and_blobs():
    sig = "-----BEGIN PGP SIGNATURE-----\n" + "A" * 400
    v = {"a": None, "b": "", "c": [], "d": {}, "e": 0, "f": False,
         "issues_url": "https://api.github.com/repos/x/y/issues{/number}", "html_url": "https://github.com/x/y",
         "sig": sig}
    assert jsonc.prune(v) == {"e": 0, "f": False, "html_url": "https://github.com/x/y",
                              "sig": f"<{len(sig):,}-char blob omitted>"}


# ---------- logs ----------

LOG = "\n".join(
    [f"2026-10-12T09:00:{i:02d}.000Z INFO  [api] GET /x 200 {10 + i}ms user=u{1000 if i % 2 else 1100 + i}" for i in range(40)]
    + [f"2026-10-12T09:01:{i:02d}.000Z ERROR [api] GET /x 503 {i}ms user=u2000" for i in range(6)]
    + ["2026-10-12T09:02:00.000Z INFO  [deployer] deployed api version 2.0.1",
       "2026-10-12T09:02:01.000Z ERROR [api] boom", "java.lang.IllegalStateException: bad", "    at A.b(A.java:1)"])


def test_log_patterns_keep_rare_lines_and_split_low_cardinality_slots():
    out = logc.compress(LOG)
    assert "[x40 2026-10-12T09:00:00.000Z→09:00:39.000Z] INFO  [api] GET /x 200 <1>ms user=<2>" in out
    assert "<1>: 10-49, avg 29.5" in out
    assert "<2>: 21 distinct; most common u1000 x20" in out
    assert "[x6 " in out and " 503 " in out  # 503 stays a separate pattern from 200
    assert "2026-10-12T09:02:00.000Z INFO  [deployer] deployed api version 2.0.1" in out  # rare: verbatim
    assert "java.lang.IllegalStateException: bad\n    at A.b(A.java:1)" in out  # continuation lines kept


def test_log_entries_attach_continuation_lines():
    es = logc.entries(LOG)
    assert len(es) == 48 and es[-1][1].endswith("at A.b(A.java:1)")


# ---------- selection, detection, API ----------

def test_select_keeps_header_and_respects_budget():
    units = ["HEADER"] + [f"row {i} filler text" for i in range(50)] + ["row about bihar jio subscribers"]
    out = select(units, "How many Jio subscribers in Bihar?", budget_chars=60, keep={0})
    assert out.startswith("HEADER") and "bihar" in out and len(out) < 120


def test_detect():
    assert detect('{"a": 1}') == "json" and detect(LOG) == "log" and detect("Just some text.\nMore.") == "text"


def test_compress_methods():
    t = (CTX / "telecom_nov2025.json").read_text()
    assert compress(t, "raw") == t
    assert len(compress(t, "smart")) < 0.2 * len(t)
    small = compress(t, "smart+select", query="Airtel subscribers in Tamil Nadu")
    assert "Tamil Nadu,Airtel" in small and len(small) < len(compress(t, "smart"))
    with pytest.raises(ValueError):
        compress(t, "select")


# ---------- grading ----------

def test_grade():
    num = {"grade": "number", "answer": 15.83}
    assert bench.grade(num, "15.83 million") == "correct"
    assert bench.grade(num, "15,830,000") == "correct"
    assert bench.grade(num, "15.9") == "wrong"
    assert bench.grade(num, "NOT_FOUND") == "abstained"
    assert bench.grade({"grade": "text", "answer": "U.P. (East)"}, "U.P. (East)") == "correct"
    assert bench.grade({"grade": "not_found", "answer": "NOT_FOUND"}, "NOT FOUND") == "correct"
    assert bench.grade({"grade": "not_found", "answer": "NOT_FOUND"}, "12") == "wrong"
