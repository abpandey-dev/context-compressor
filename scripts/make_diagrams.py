"""Draw docs/how-it-works.svg and docs/what-we-get.svg from results/findings.json."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from diagram_kit import BODY, INK, MUTED, arrow, box, card, hbar, lane, lines, panel, svg, t  # noqa: E402

F = json.loads((ROOT / "results" / "findings.json").read_text())
M, K, C = F["methods"], F["by_kind"], F["by_category"]

b = [lane(24, 104, 1152, 250, "blue", "COMPRESS · before the tool output reaches the model")]
b.append(box(44, 144, 200, 180, "slate", "Tool output",
             ["API JSON, logs,", "documents: whatever", "a tool returns", "", "-> the compressor", "for its type"], plain=True))
b.append(box(276, 144, 300, 180, "blue", "JSON: lossless tables",
             ["list of objects -> one header", "+ one row per object;", "nested fields flattened;",
              "same-in-every-row written once;", "drops nulls, URL templates, blobs"]))
b.append(box(596, 144, 290, 180, "violet", "Logs: pattern mining",
             ["varying parts masked;", "rare lines kept verbatim;", "repeats -> count, time range,",
              "ranges, most common values"]))
b.append(box(906, 144, 250, 180, "teal", "Optional: select",
             ["BM25 against the", "question keeps only", "the relevant rows,", "entries or chunks"]))
b += [arrow(244, 234, 272, 234), arrow(886, 234, 902, 234)]
b.append(t(276, 344, "Documents: whitespace, page numbers and repeated headers are cleaned up", 12, MUTED))
b.append(lane(24, 374, 1152, 266, "amber", "MEASURE · does the model still get the answer?"))
b.append(box(44, 414, 260, 196, "slate", f"{F['questions']} questions",
             [f"{F['contexts']} real contexts: GitHub API,", "TRAI tables and press", "releases, an incident log",
              "answers computed in code"], plain=True))
b.append(box(330, 414, 250, 196, "amber", "6 methods",
             ["raw, minify, smart,", "select, smart + select,", "LLM summary (Claude", "compresses it first)"]))
b.append(box(606, 414, 260, 196, "blue", "Claude Haiku 5.5",
             ["answers from the context", "or says NOT_FOUND;", "exact prompt sizes from", "Claude's own tokenizer"]))
b.append(box(892, 414, 264, 196, "green", "Graded in code",
             ["no LLM judge: numbers,", "IDs and names compared", "to the truth; 'abstained'", "vs 'wrong' kept apart"]))
b += [arrow(304, 512, 326, 512), arrow(580, 512, 602, 512), arrow(866, 512, 888, 512)]
(ROOT / "docs" / "how-it-works.svg").write_text(svg(
    1200, 660, "Context compressor: how it works",
    "Shrink what tools hand an LLM, then prove the answers survive", "\n".join(b)))

sm, raw = M["smart"], M["raw"]
b = [panel(24, 104, 600, 330, "Prompt size and accuracy, per method", "bars: average prompt tokens per question")]
colors = {"raw": "#94A3B8", "minify": "#CBD5E1", "smart": "#2563EB", "select": "#D97706", "smart+select": "#0F766E",
          "llm_summary": "#EA580C"}
names = {"raw": "Raw", "minify": "Minify", "smart": "Smart", "select": "Select", "smart+select": "Smart + select",
         "llm_summary": "LLM summary"}
for i, m in enumerate(["raw", "minify", "smart", "select", "smart+select", "llm_summary"]):
    r = M[m]
    b.append(hbar(34, 168 + i * 42, names[m], r["input_tokens"], raw["input_tokens"], 250, colors[m],
                  f"{r['input_tokens'] / 1000:.1f}K", label_w=130, bold=m == "smart"))
    b.append(t(600, 187 + i * 42, f"{r['correct']}/{r['questions']} correct", 13, INK if m == "smart" else BODY,
               700 if m == "smart" else None, "end"))
b.append(panel(648, 104, 528, 330, "Where the answers go", "share answered correctly"))
cats = [("lookup", "Look up one value"), ("aggregate", "Count / total / max"), ("absent", "Not in the context")]
b.append(t(940, 172, "Smart", 12, MUTED, 700, "end"))
b.append(t(1030, 172, "Select", 12, MUTED, 700, "end"))
b.append(t(1140, 172, "LLM sum.", 12, MUTED, 700, "end"))
for i, (c, label) in enumerate(cats):
    y = 210 + i * 40
    b.append(t(668, y, label, 14, INK, 600))
    for x, m in [(940, "smart"), (1030, "select"), (1140, "llm_summary")]:
        v = C[c][m]
        b.append(t(x, y, f"{v:.0f}%", 14, "#15803D" if v >= 95 else ("#B45309" if v >= 75 else "#B91C1C"), 700, "end"))
b.append(lines(668, 352, ["Partial context (select, summaries) loses counts", "and totals; smart keeps them, because the counts",
                          "are computed before the model sees the log."], 13, BODY, 22))
b.append(card(24, 458, 276, 182, "blue", f"-{sm['token_reduction']:.0f}%", "tokens with smart compression",
              [f"{sm['correct']}/{sm['questions']} correct, same as raw", f"${raw['cost_per_q']:.4f} -> ${sm['cost_per_q']:.4f}",
               "per question"], big_size=34))
lg = K["Logs"]
b.append(card(316, 458, 276, 182, "violet", f"-{lg['smart']['reduction']:.0f}%", "on a 1,703-line incident log",
              [f"{lg['raw']['tokens'] / 1000:.0f}K -> {lg['smart']['tokens'] / 1000:.1f}K tokens; raw made the",
               "model miscount (36 vs 37);", "the pattern count was exact"]))
b.append(card(608, 458, 276, 182, "green", "Lossless", "JSON tables decode exactly",
              ["back to the original: 5 real", "API responses + 3,000", "random values, tested in CI"], big_size=30))
b.append(card(900, 458, 276, 182, "amber", "'About 48'", "an LLM summary's count",
              ["the log had 47 503s; the", "summary rounded it, and", "max latency 884 became 900"], big_size=30))
(ROOT / "docs" / "what-we-get.svg").write_text(svg(
    1200, 660, "Context compressor: what we get from it",
    f"{F['questions']} questions · 7 real contexts · 6 methods · whole benchmark cost ${F['eval_cost']:.2f} on Claude Haiku 5.5",
    "\n".join(b)))
print("diagrams written")
