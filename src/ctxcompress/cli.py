"""ctxc: compress a file (or stdin) and print the result; sizes go to stderr.

    ctxc api_response.json
    ctxc app.log --method smart+select --query "how many 503s from payment-svc?"
    curl -s https://api.github.com/users/octocat/repos | ctxc - --stats
"""

from __future__ import annotations

import argparse
import sys

from . import METHODS, compress, detect


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ctxc", description="Shrink tool outputs, logs and documents for an LLM.")
    ap.add_argument("file", help="path, or - for stdin")
    ap.add_argument("--method", "-m", default="smart", choices=METHODS)
    ap.add_argument("--query", "-q", help="the question (needed for select methods)")
    ap.add_argument("--budget", type=float, help="share of the input to keep for select methods")
    ap.add_argument("--stats", action="store_true", help="print sizes only")
    a = ap.parse_args(argv)
    text = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    out = compress(text, a.method, query=a.query, budget=a.budget)
    if not a.stats:
        sys.stdout.write(out + "\n")
    print(f"[{detect(text)}] {len(text):,} -> {len(out):,} chars ({1 - len(out) / max(len(text), 1):.0%} smaller)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
