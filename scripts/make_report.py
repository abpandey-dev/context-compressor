"""Turn results/<model>/... into results/summary.csv, results/findings.json and the README charts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ctxcompress import bench  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-5-5"
IMG = ROOT / "docs" / "images"
COLORS = {"raw": "#8a8984", "minify": "#b9b8b2", "smart": "#2a78d6", "select": "#eda100", "smart+select": "#1baf7a",
          "llm_summary": "#eb6834"}
KIND = {".json": "JSON (API responses)", ".log": "Logs", ".txt": "Documents"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "text.color": INK, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
                     "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False})


def load() -> pd.DataFrame:
    rows = [json.loads(f.read_text()) for f in (ROOT / "results" / MODEL).glob("*/*.json")]
    d = pd.DataFrame(rows)
    tasks = {t["id"]: t for t in bench.load_tasks()}
    d["verdict"] = [bench.grade(tasks[r.task], r.answer) for r in d.itertuples()]  # always grade with current rules
    d["kind"] = d["context"].map(lambda c: KIND[Path(c).suffix])
    return d


def main():
    d = load()
    tasks = bench.load_tasks()
    summ_dir = ROOT / "results" / MODEL / "llm_summary" / "_summaries"
    summ = {f.stem: json.loads(f.read_text()) for f in summ_dir.glob("*.json")}
    summ_cost = sum(s["cost"] for s in summ.values())
    n_q = {c: sum(t["context"] == c for t in tasks) for c in summ}
    # LLM summary: a context's summary is made once and shared by its questions, so spread its cost over them
    share = {c: summ[c]["cost"] / n_q[c] for c in summ}
    d["total_cost"] = d["cost"] + d.apply(lambda r: share.get(r["context"], 0) if r["method"] == "llm_summary" else 0,
                                          axis=1)
    raw_tok = d[d.method == "raw"].set_index("task")["input_tokens"]
    s = d.groupby("method").agg(questions=("task", "size"), correct=("verdict", lambda v: (v == "correct").sum()),
                                abstained=("verdict", lambda v: (v == "abstained").sum()),
                                wrong=("verdict", lambda v: (v == "wrong").sum()),
                                input_tokens=("input_tokens", "mean"), cost_per_q=("total_cost", "mean"))
    s["accuracy"] = s["correct"] / s["questions"] * 100
    s["token_reduction"] = (1 - s["input_tokens"] / raw_tok.mean()) * 100
    s = s.reindex([m for m in bench.METHODS if m in s.index])
    s.round(4).to_csv(ROOT / "results" / "summary.csv")
    print(s.round(3).to_string())

    by_kind = d.groupby(["kind", "method"]).agg(acc=("verdict", lambda v: (v == "correct").mean() * 100),
                                                tok=("input_tokens", "mean")).reset_index()
    raw_k = by_kind[by_kind.method == "raw"].set_index("kind")["tok"]
    by_kind["reduction"] = by_kind.apply(lambda r: (1 - r.tok / raw_k[r.kind]) * 100, axis=1)
    by_cat = d.groupby(["category", "method"]).verdict.apply(lambda v: (v == "correct").mean() * 100).unstack()
    print(by_kind.round(1).to_string())
    print(by_cat.round(0).reindex(columns=s.index).to_string())

    keep = ["task", "context", "category", "method", "model", "truth", "answer", "verdict", "input_tokens",
            "output_tokens", "cost", "stop_reason"]
    with (ROOT / "results" / f"answers_{MODEL}.jsonl").open("w") as f:
        for r in d.sort_values(["method", "task"])[keep].to_dict("records"):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (ROOT / "results" / f"summaries_{MODEL}.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))
    misses = d[d.verdict != "correct"].sort_values(["method", "task"])
    misses[["method", "task", "category", "truth", "answer", "verdict"]].to_csv(ROOT / "results" / "misses.csv",
                                                                                index=False)
    findings = {
        "model": MODEL,
        "questions": len(tasks),
        "contexts": len({t["context"] for t in tasks}),
        "methods": {m: {k: (int(v) if k in ("questions", "correct", "abstained", "wrong") else round(float(v), 4))
                        for k, v in row.items()} for m, row in s.iterrows()},
        "by_kind": {k: {r.method: {"accuracy": round(r.acc, 1), "tokens": round(r.tok), "reduction": round(r.reduction, 1)}
                        for r in g.itertuples()} for k, g in by_kind.groupby("kind")},
        "by_category": {c: {m: round(float(v), 1) for m, v in row.items() if pd.notna(v)} for c, row in by_cat.iterrows()},
        "summary_cost": round(summ_cost, 4),
        "eval_cost": round(float(d["cost"].sum() + summ_cost), 4),
    }
    (ROOT / "results" / "findings.json").write_text(json.dumps(findings, indent=1))
    charts(s, by_kind, by_cat)


def charts(s, by_kind, by_cat):
    IMG.mkdir(parents=True, exist_ok=True)
    # 1. the trade-off: tokens per question vs accuracy
    fig, ax = plt.subplots(figsize=(8, 4.4))
    place = {"raw": ((10, 4), "left", "bottom"), "minify": ((0, -12), "center", "top"),
             "llm_summary": ((0, 12), "center", "bottom")}
    for m, r in s.iterrows():
        ax.scatter(r.input_tokens, r.accuracy, s=140, color=COLORS[m], zorder=3, edgecolor="white", linewidth=1.5)
        xy, ha, va = place.get(m, ((9, -4), "left", "top"))
        ax.annotate(f"{bench.LABELS[m]}\n{r.accuracy:.0f}% · {r.input_tokens / 1000:.1f}K tokens",
                    (r.input_tokens, r.accuracy), textcoords="offset points", xytext=xy, fontsize=8.5,
                    color=INK2, va=va, ha=ha)
    ax.set_xscale("log")
    ax.set_xlabel("average prompt size per question (tokens, log scale)")
    ax.set_ylabel("questions answered correctly (%)")
    lo = min(s.accuracy.min() - 8, 60)
    ax.set_ylim(lo, 103)
    ax.set_xlim(s.input_tokens.min() * 0.6, s.input_tokens.max() * 3.2)
    ax.set_title(f"Fewer tokens, same answers? {len(bench.load_tasks())} questions, Claude Haiku 5.5")
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(IMG / "tradeoff.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 2. token reduction per content type
    ms = ["minify", "smart", "select", "smart+select", "llm_summary"]
    kinds = list(KIND.values())
    fig, ax = plt.subplots(figsize=(8, 3.8))
    w = 0.16
    for j, m in enumerate(ms):
        vals = [by_kind[(by_kind.kind == k) & (by_kind.method == m)].reduction.mean() for k in kinds]
        xs = [i + (j - 2) * w for i in range(len(kinds))]
        ax.bar(xs, vals, width=w, color=COLORS[m], label=bench.LABELS[m])
        for x, v in zip(xs, vals):
            ax.text(x, v + 1.5, f"{v:.0f}", ha="center", fontsize=7.5, color=INK2)
    ax.set_xticks(range(len(kinds)), kinds)
    ax.set_ylim(0, 108)
    ax.set_ylabel("fewer tokens than raw (%)")
    ax.set_title("Token reduction by content type")
    ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.1), fontsize=8.5)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(IMG / "reduction_by_type.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. accuracy by question type
    cats = ["lookup", "aggregate", "absent"]
    names = {"lookup": "Look up one value", "aggregate": "Count / total / max\n(needs the whole context)",
             "absent": "Answer isn't there\n(must say NOT_FOUND)"}
    fig, ax = plt.subplots(figsize=(8, 3.8))
    order = [m for m in bench.METHODS if m in by_cat.columns]
    w = 0.13
    for j, m in enumerate(order):
        vals = [by_cat.loc[c, m] for c in cats]
        xs = [i + (j - (len(order) - 1) / 2) * w for i in range(len(cats))]
        ax.bar(xs, vals, width=w, color=COLORS[m], label=bench.LABELS[m])
    ax.set_xticks(range(len(cats)), [names[c] for c in cats])
    ax.set_ylim(0, 105)
    ax.set_ylabel("correct (%)")
    ax.set_title("Where each method loses answers")
    ax.legend(frameon=False, ncol=6, loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(IMG / "accuracy_by_question.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("charts written")


if __name__ == "__main__":
    main()
