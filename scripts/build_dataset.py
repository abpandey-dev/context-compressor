"""Build the benchmark: contexts (what a tool would hand an LLM) + questions whose answers are computed in code.

Contexts
  telecom_nov2025.json   API-style JSON: TRAI subscribers + active % for every circle x operator, Nov 2025
  telecom_series.json    API-style JSON: monthly subscribers, 3 circles x 4 operators, Feb 2024 - Nov 2025
  github_repos.json      GitHub REST API: GET /users/abpandey-dev/repos (as returned)
  github_runs.json       GitHub REST API: GET /repos/abpandey-dev/telecom-india/actions/runs
  github_commits.json    GitHub REST API: GET /repos/abpandey-dev/telecom-india/commits
  app.log                synthetic service log (seeded): a bad deploy, 503s, a rollback, one-off errors
  trai_jul_aug_2026.txt  text of TRAI's July and August 2026 press releases (main sections)

Needs: ../telecom-india/data/processed (published) and, for the document, its downloaded PDFs.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CTX = ROOT / "data" / "contexts"
TELECOM = ROOT.parent / "telecom-india"
OPS = ["Jio", "Airtel", "Vi", "BSNL"]
NF = "NOT_FOUND"
tasks: list[dict] = []


def task(ctx, q, answer, kind, category):
    tasks.append({"id": f"{ctx.split('.')[0]}-{sum(t['context'] == ctx for t in tasks) + 1:02d}", "context": ctx,
                  "question": q, "answer": answer, "grade": kind, "category": category})


def write_json(name, obj):
    (CTX / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# ---------------- telecom (TRAI tables as an API response) ----------------

def telecom():
    m = pd.read_csv(TELECOM / "data/processed/mobile.csv")
    a = pd.read_csv(TELECOM / "data/processed/active.csv")
    m = m[m.operator.isin(OPS)]
    nov = m[m.month == "2025-11-01"].merge(a, on=["month", "lsa", "operator"], how="left")
    nov = nov.sort_values(["lsa", "operator"])
    recs = [{"month": "2025-11", "circle": r.lsa, "operator": r.operator, "subscribers": int(r.subscribers),
             "active_pct": None if pd.isna(r.active_pct) else round(float(r.active_pct), 2),
             "unit": "subscribers", "source": "TRAI Telecom Subscription Data, Annexure II/III", "revised": False}
            for r in nov.itertuples()]
    write_json("telecom_nov2025.json", {"request": {"endpoint": "/v1/subscribers", "month": "2025-11",
                                                    "segment": "wireless_mobile"},
                                        "count": len(recs), "records": recs, "next_page": None})
    ctx = "telecom_nov2025.json"
    p = nov.pivot_table(index="lsa", columns="operator", values="subscribers")
    act = nov.pivot_table(index="lsa", columns="operator", values="active_pct")
    task(ctx, "How many mobile subscribers did Airtel have in Tamil Nadu?", int(p.loc["Tamil Nadu", "Airtel"]),
         "number", "lookup")
    task(ctx, "What was BSNL's active-SIM percentage (active_pct) in Kerala?", float(act.loc["Kerala", "BSNL"]),
         "number", "lookup")
    task(ctx, "Which circle had the most Jio subscribers?", p["Jio"].idxmax(), "text", "aggregate")
    task(ctx, "In which circle was Vi's active_pct the lowest?", act["Vi"].idxmin(), "text", "aggregate")
    d = p.loc["Delhi"]
    task(ctx, "In Delhi, which operator had more subscribers, Jio or Airtel?", "Jio" if d.Jio > d.Airtel else "Airtel",
         "text", "lookup")
    task(ctx, "In how many circles did Jio have more subscribers than Airtel?", int((p.Jio > p.Airtel).sum()),
         "number", "aggregate")
    task(ctx, "How many subscribers did Jio have in Sikkim?", NF, "not_found", "absent")

    circles = ["Bihar", "Mumbai", "Delhi"]
    s = m[m.lsa.isin(circles) & (m.month <= "2025-11-01")].sort_values(["month", "lsa", "operator"])
    recs = [{"month": r.month[:7], "circle": r.lsa, "operator": r.operator, "subscribers": int(r.subscribers),
             "source_report": "current" if r.source == "cur" else "next-month report"} for r in s.itertuples()]
    write_json("telecom_series.json", {"request": {"endpoint": "/v1/subscribers/series", "circles": circles,
                                                   "from": "2024-02", "to": "2025-11"},
                                       "count": len(recs), "records": recs, "next_page": None})
    ctx = "telecom_series.json"
    q = s.pivot_table(index=["lsa", "month"], columns="operator", values="subscribers")
    task(ctx, "How many subscribers did Vi have in Mumbai in March 2025?", int(q.loc[("Mumbai", "2025-03-01"), "Vi"]),
         "number", "lookup")
    ch = q.loc[("Bihar", "2025-11-01"), "Jio"] - q.loc[("Bihar", "2024-02-01"), "Jio"]
    task(ctx, "By how many subscribers did Jio's base in Bihar change between February 2024 and November 2025? "
              "Give the signed difference.", int(ch), "number", "aggregate")
    mu = q.loc["Mumbai"]["Airtel"]
    task(ctx, "In which month did Airtel have the most subscribers in Mumbai? Answer as YYYY-MM.",
         mu.idxmax()[:7], "text", "aggregate")
    task(ctx, "How many subscribers did Vi have in Mumbai in December 2025?", NF, "not_found", "absent")


# ---------------- GitHub API (as returned) ----------------

def github():
    raw = ROOT / "data" / "raw"
    repos = json.loads((raw / "github_repos.json").read_text())
    (CTX / "github_repos.json").write_text((raw / "github_repos.json").read_text())
    ctx = "github_repos.json"
    latest = max(repos, key=lambda r: r["pushed_at"])
    task(ctx, "Which repository was pushed to most recently?", latest["name"], "text", "aggregate")
    nf = next(r for r in repos if r["name"] == "netflix-insights")
    task(ctx, "What is the size (in KB) of the netflix-insights repository?", nf["size"], "number", "lookup")
    task(ctx, "How many repositories have Python as their main language?",
         sum(r["language"] == "Python" for r in repos), "number", "aggregate")
    jup = [r["name"] for r in repos if r["language"] == "Jupyter Notebook"]
    task(ctx, "Which repository's main language is Jupyter Notebook?", jup[0], "text", "lookup")
    te = next(r for r in repos if r["name"] == "telecom-india")
    task(ctx, "What is the default branch of the telecom-india repository?", te["default_branch"], "text", "lookup")
    rp = next(r for r in repos if r["name"] == "rail-punctuality")
    task(ctx, "When was the rail-punctuality repository created? Give the full timestamp.", rp["created_at"],
         "text", "lookup")
    task(ctx, "How many stars does the voice-agent repository have?", NF, "not_found", "absent")

    runs = json.loads((raw / "github_runs.json").read_text())
    (CTX / "github_runs.json").write_text((raw / "github_runs.json").read_text())
    ctx = "github_runs.json"
    w = {r["run_number"]: r for r in runs["workflow_runs"]}
    task(ctx, "How many of the listed workflow runs did not succeed?",
         sum(r["conclusion"] != "success" for r in w.values()), "number", "aggregate")
    task(ctx, "What was the first line of the head commit message for run number 3?",
         w[3]["head_commit"]["message"].splitlines()[0], "text", "lookup")
    task(ctx, "What is the full head SHA of run number 6?", w[6]["head_sha"], "text", "lookup")
    task(ctx, "What is the run_started_at timestamp of run number 4? Give the full timestamp.", w[4]["run_started_at"],
         "text", "lookup")
    task(ctx, "Which branch did run number 1 run on?", w[1]["head_branch"], "text", "lookup")

    commits = json.loads((raw / "github_commits.json").read_text())
    (CTX / "github_commits.json").write_text((raw / "github_commits.json").read_text())
    ctx = "github_commits.json"
    by = {c["sha"][:7]: c for c in commits}
    task(ctx, "How many commits are listed?", len(commits), "number", "aggregate")
    task(ctx, "What is the full SHA of the parent of commit 5ea7b66?", by["5ea7b66"]["parents"][0]["sha"],
         "text", "lookup")
    idx = next(c for c in commits if "report index" in c["commit"]["message"])
    task(ctx, "What is the short (7-character) SHA of the commit that added the TRAI report index?", idx["sha"][:7],
         "text", "lookup")
    task(ctx, "What is the email address of the committer of commit 098d1b3?",
         by["098d1b3"]["commit"]["committer"]["email"], "text", "lookup")
    task(ctx, "Which commit in the list is a merge commit (has two parents)? Give its short SHA.",
         next((c["sha"][:7] for c in commits if len(c["parents"]) > 1), NF),
         "not_found" if all(len(c["parents"]) < 2 for c in commits) else "text", "absent")


# ---------------- synthetic service log ----------------

def app_log(seed=7):
    rnd = random.Random(seed)
    t0 = datetime(2026, 10, 12, 9, 0, 0)
    ev: list[tuple[datetime, str]] = []

    def at(sec):
        return t0 + timedelta(seconds=sec, milliseconds=rnd.randint(0, 999))

    def hexid():
        return "".join(rnd.choice("0123456789abcdef") for _ in range(12))

    deploy, rollback = 2 * 3600 // 2 + 131, 3600 + 1900  # 10:02:11, 10:31:40
    services = ["checkout-api", "payment-svc", "inventory-svc"]
    for s in range(0, 7200, 30):
        for svc in services:
            ev.append((at(s), f"INFO  [{svc}] health check ok latency={rnd.randint(1, 9)}ms"))
    fail_hc = [2711, 2741, 2771]
    for s in fail_hc:
        ev.append((at(s), "WARN  [inventory-svc] health check FAILED: redis ping timeout"))
    for s in range(0, 7200, 300):
        for svc in services:
            ev.append((at(s), f"DEBUG [{svc}] metrics cpu={rnd.uniform(8, 70):.1f}% "
                              f"mem={rnd.randint(380, 900)}MB conns={rnd.randint(10, 90)}"))
    heavy, rare_user = "u4821", "u7302"
    users = [f"u{rnd.randint(1000, 9999)}" for _ in range(400)]
    users = [u for u in users if u not in (heavy, rare_user)]
    cart_users = []
    for _ in range(430):
        u = rnd.choice(users)
        cart_users.append(u)
    cart_users += [heavy] * 37 + [rare_user] * 2
    rnd.shuffle(cart_users)
    for u in cart_users:
        ms = rnd.randint(8, 480)
        ev.append((at(rnd.randint(0, 7199)), f"INFO  [checkout-api] GET /api/v1/cart/{rnd.randint(10000, 99999)} "
                                             f"200 {ms}ms user={u} req={hexid()}"))
    pay_ok_ms, n503 = [], 0
    pool_warns = 0
    traces = 0
    for _ in range(260):
        s = rnd.randint(0, 7199)
        u = rnd.choice(users)
        if deploy <= s < rollback and rnd.random() < 0.75:
            n503 += 1
            ev.append((at(s), f"ERROR [payment-svc] POST /api/v1/pay 503 upstream timeout after 5000ms "
                              f"provider=bankgw user={u} req={hexid()}"))
            if rnd.random() < 0.35:
                pool_warns += 1
                ev.append((at(s), "WARN  [payment-svc] db connection pool exhausted (max=50), waiting for a free "
                                  "connection"))
            if rnd.random() < 0.2:
                traces += 1
                ev.append((at(s), "ERROR [payment-svc] unhandled exception in PaymentController.charge\n"
                                  "java.net.SocketTimeoutException: Read timed out\n"
                                  "    at java.net.SocketInputStream.read(SocketInputStream.java:183)\n"
                                  "    at com.shop.pay.BankGatewayClient.charge(BankGatewayClient.java:212)\n"
                                  "    at com.shop.pay.PaymentController.charge(PaymentController.java:88)"))
        else:
            ms = rnd.randint(40, 900)
            pay_ok_ms.append(ms)
            ev.append((at(s), f"INFO  [payment-svc] POST /api/v1/pay 200 {ms}ms provider=bankgw user={u} "
                              f"req={hexid()}"))
    for _ in range(150):
        ev.append((at(rnd.randint(0, 7199)), f"INFO  [inventory-svc] GET /api/v1/stock/SKU-{rnd.randint(10000, 99999)} "
                                             f"200 {rnd.randint(3, 120)}ms req={hexid()}"))
    bad_req = hexid()
    ev.append((t0 + timedelta(seconds=2833, milliseconds=412),
               f"ERROR [inventory-svc] GET /api/v1/stock/SKU-88231 500 NullPointerException in StockMapper.toDto "
               f"req={bad_req}"))
    ev.append((t0 + timedelta(seconds=deploy), "INFO  [deployer] deployed payment-svc version 2.14.1 "
                                               "(commit 9f3c2ab) by ci-bot"))
    ev.append((t0 + timedelta(seconds=rollback), "INFO  [deployer] rolled back payment-svc to version 2.14.0 "
                                                 "by oncall-asha"))
    ev.append((t0 + timedelta(seconds=5140, milliseconds=77), "WARN  [inventory-svc] disk usage 91% on "
                                                              "/var/lib/inventory"))
    ev.sort(key=lambda e: e[0])
    mem = [int(m) for _, s in ev if "[payment-svc] metrics" in s for m in re.findall(r"mem=(\d+)MB", s)]
    lines = [f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z {s}" for t, s in ev]
    (CTX / "app.log").write_text("\n".join(lines) + "\n")
    first503 = next(t for t, s in ev if " 503 " in s)
    ctx = "app.log"
    task(ctx, "How many 503 responses did payment-svc return?", n503, "number", "aggregate")
    task(ctx, "Which version of payment-svc was deployed?", "2.14.1", "text", "lookup")
    task(ctx, "At what time (HH:MM:SS) was payment-svc rolled back?",
         (t0 + timedelta(seconds=rollback)).strftime("%H:%M:%S"), "text", "lookup")
    task(ctx, "How many times was the 'db connection pool exhausted' warning logged?", pool_warns, "number",
         "aggregate")
    task(ctx, "What was the request id (req) of the inventory-svc request that returned HTTP 500?", bad_req,
         "text", "lookup")
    task(ctx, "Which user made the most checkout cart requests?", heavy, "text", "aggregate")
    task(ctx, f"How many cart requests did user {heavy} make?", 37, "number", "aggregate")
    task(ctx, f"How many cart requests did user {rare_user} make?", 2, "number", "aggregate")
    task(ctx, "What was the highest latency, in ms, of a successful (200) payment request?", max(pay_ok_ms),
         "number", "aggregate")
    task(ctx, "At what time (HH:MM:SS) did payment-svc return its first 503?", first503.strftime("%H:%M:%S"),
         "text", "lookup")
    task(ctx, "Which exception class appears in the payment-svc stack traces?", "SocketTimeoutException",
         "text", "lookup")
    task(ctx, "How many inventory-svc health checks failed?", len(fail_hc), "number", "aggregate")
    task(ctx, "What was the highest memory usage (MB) reported in payment-svc metrics?", max(mem), "number",
         "aggregate")
    task(ctx, "What was the CPU usage reported by search-svc?", NF, "not_found", "absent")
    print(f"app.log: {len(lines)} entries, {n503} x 503, {pool_warns} pool warnings, {traces} stack traces")


# ---------------- TRAI press releases (document) ----------------

def trai_doc():
    import pdfplumber

    reports = [("July 2026", "PR_No116of2026_0.pdf"), ("August 2026", "PR_No125of2026_0.pdf")]
    parts, facts = [], {}
    for month, f in reports:
        with pdfplumber.open(TELECOM / "data/raw" / f) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:18])
        parts.append(f"=== TRAI press release: Telecom Subscription Data at the end of {month} ===\n{text}")
        mon = month.split()[0]
        one = lambda pat: re.search(pat, text, re.S).group(1)  # noqa: E731
        facts[month] = {
            "operators": int(one(r"information received from (\d+) operators")),
            "mnp": float(one(r"([\d.]+) million subscribers submitted their\s+requests for Mobile Number Portability")),
            "active": float(one(rf"in {mon} 2026 was ([\d.]+) million")),
            "m2m_end": float(one(r"M2M cellular mobile connections increased from [\d.]+\s+million.*?to ([\d.]+)"
                                 r"\s+million")),
            "total_tel": float(one(r"Total Telephone Subscribers \(Million\) [\d.]+ [\d.]+ ([\d.]+)")),
            "teledensity": float(one(r"Overall Tele-density@ with M2M\s+[\d.]+% [\d.]+% ([\d.]+)%")),
            "airtel_wired": float(one(r"Top Five Fixed Wired Access Broadband.*?Bharti Airtel Ltd\. ([\d.]+)")),
        }
    (CTX / "trai_jul_aug_2026.txt").write_text("\n\n".join(parts) + "\n")
    ctx = "trai_jul_aug_2026.txt"
    jul, aug = facts["July 2026"], facts["August 2026"]
    task(ctx, "How many operators reported broadband data for August 2026?", aug["operators"], "number", "lookup")
    task(ctx, "How many operators reported broadband data for July 2026?", jul["operators"], "number", "lookup")
    task(ctx, "How many million MNP (number portability) requests were submitted in August 2026?", aug["mnp"],
         "number", "lookup")
    task(ctx, "How many million MNP (number portability) requests were submitted in July 2026?", jul["mnp"],
         "number", "lookup")
    task(ctx, "How many million active wireless (mobile) subscribers were there on the date of peak VLR in "
              "August 2026?", aug["active"], "number", "lookup")
    task(ctx, "How many million M2M cellular mobile connections were there at the end of July 2026?",
         jul["m2m_end"], "number", "lookup")
    task(ctx, "What was the total number of telephone subscribers (million) at the end of August 2026?",
         aug["total_tel"], "number", "lookup")
    task(ctx, "What was the overall tele-density with M2M connections at the end of July 2026 (%)?",
         jul["teledensity"], "number", "lookup")
    task(ctx, "How many million fixed wired broadband subscribers did Bharti Airtel have at the end of July 2026?",
         jul["airtel_wired"], "number", "lookup")
    task(ctx, "By how many million did the M2M connection count change from the end of July to the end of "
              "August 2026?", round(aug["m2m_end"] - jul["m2m_end"], 2), "number", "aggregate")
    task(ctx, "What was Jio's average 5G download speed in August 2026?", NF, "not_found", "absent")
    print("TRAI facts:", json.dumps(facts))


def main():
    CTX.mkdir(parents=True, exist_ok=True)
    telecom()
    github()
    app_log()
    trai_doc()
    out = ROOT / "data" / "tasks.jsonl"
    out.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    by = pd.DataFrame(tasks).groupby(["context", "category"]).size().unstack(fill_value=0)
    print(by.to_string())
    print(f"{len(tasks)} tasks -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
