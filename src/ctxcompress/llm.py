"""Claude calls used by the benchmark: exact token counts, answering a question, and the LLM-summary baseline."""

from __future__ import annotations

import json
import threading
import time

import anthropic

MODEL = "claude-haiku-5-5"
PRICES = {  # USD per million tokens (input, output), prompts up to 100K tokens
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

SYSTEM = ("You answer questions about the context you are given: a tool output, a log or a document, possibly in a "
          "compressed form that describes its own format. Use only the context. If it does not contain the answer, "
          "answer NOT_FOUND. Give only the answer (a number, name, ID, date or short phrase), with no explanation.")
SUMMARY_SYSTEM = ("You compress tool outputs, logs and documents for another AI model, which will later answer "
                  "questions about them that you can't see. Keep every number, name, ID, date and status that could "
                  "matter; drop boilerplate and repetition. Aim for at most a quarter of the original length.")
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"],
                 "additionalProperties": False}


class _Pace:
    """Keep under the account's limits: 100 requests and 500K input tokens a minute (we aim for 80 and 400K)."""

    def __init__(self, per_minute: int = 80, tokens_per_minute: int = 400_000):
        self.gap, self.tpm, self.next, self.lock = 60 / per_minute, tokens_per_minute, 0.0, threading.Lock()

    def wait(self, tokens: int = 0):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + max(self.gap, 60 * tokens / self.tpm)
        time.sleep(max(0.0, start - now))


PACE = _Pace()


def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=8)


def cost(model: str, usage) -> float:
    i, o = PRICES[model]
    inp = usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0)
    return (inp * i + usage.output_tokens * o) / 1e6


def prompt(context: str, question: str) -> str:
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


def count_tokens(c: anthropic.Anthropic, text: str, model: str = MODEL, system: str | None = None) -> int:
    kw = {"system": system} if system else {}
    PACE.wait()
    return c.messages.count_tokens(model=model, messages=[{"role": "user", "content": text}], **kw).input_tokens


def _create(c, model, **kw):
    est = len(kw.get("system", "")) // 3 + sum(len(m["content"]) for m in kw["messages"]) // 3  # rough token estimate
    for attempt in range(8):
        PACE.wait(est)
        try:
            if model in FALLBACK_MODELS:  # server-side fallback on a safety refusal (not offered for Haiku)
                return c.beta.messages.create(model=model, betas=["server-side-fallback-2026-07-01"],
                                              fallbacks="default", **kw)
            return c.beta.messages.create(model=model, **kw)
        except anthropic.RateLimitError:
            if attempt == 7:
                raise
            time.sleep(20 * (attempt + 1))


def answer(c, context: str, question: str, model: str = MODEL, effort: str = "medium") -> dict:
    r = _create(c, model, max_tokens=8000, system=SYSTEM,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
                messages=[{"role": "user", "content": prompt(context, question)}])
    out = {"stop_reason": r.stop_reason, "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
           "cost": cost(model, r.usage), "answer": None}
    if r.stop_reason == "end_turn":
        text = next((b.text for b in r.content if b.type == "text"), "")
        try:
            out["answer"] = json.loads(text)["answer"]
        except (ValueError, KeyError):
            out["answer"] = text
    return out


def summarize(c, context: str, model: str = MODEL) -> dict:
    r = _create(c, model, max_tokens=16000, system=SUMMARY_SYSTEM, output_config={"effort": "medium"},
                messages=[{"role": "user", "content": f"<context>\n{context}\n</context>\n\nCompress this."}])
    text = "".join(b.text for b in r.content if b.type == "text")
    return {"text": text, "stop_reason": r.stop_reason, "input_tokens": r.usage.input_tokens,
            "output_tokens": r.usage.output_tokens, "cost": cost(model, r.usage)}
