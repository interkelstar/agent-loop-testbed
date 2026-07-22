"""Single-shot grid: for each (model x context), send the exact message array
once and classify the model's FIRST reaction.

Classification (mechanical):
  closes  – finished with a text answer, no tool calls
  acts    – called a tool not seen before in this conversation (progress)
  repeat  – repeated a prior text (first 80 chars) or an identical prior tool
            call — the loop-continuation signal
  error   – API error

Results append to a JSONL file, one row per (model, context, attempt).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

from .providers import Catalog, ModelSpec


def _permissive_tools(names: list[str]) -> list[dict]:
    return [{"type": "function",
             "function": {"name": n, "description": f"{n} tool",
                          "parameters": {"type": "object", "properties": {},
                                         "additionalProperties": True}}}
            for n in names]


def _post(url: str, key: str, body: dict, timeout: int) -> dict:
    headers = {"Content-Type": "application/json",
               "User-Agent": "agent-loop-testbed/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _canon_call(name: str, arguments) -> tuple[str, str]:
    """Canonical (name, args) — models like kimi pad JSON arguments with
    whitespace, which must not defeat identical-call detection."""
    try:
        return (name, json.dumps(json.loads(arguments), sort_keys=True))
    except (json.JSONDecodeError, TypeError):
        return (name, str(arguments).strip())


def classify(row: dict) -> str:
    if row.get("error"):
        return "error"
    if row.get("closed"):
        return "closes"
    if row.get("repeat_text") or row.get("repeat_call"):
        return "repeat"
    return "acts"


def run_cell(spec: ModelSpec, key: str, ctx_path: str, n: int,
             max_tokens: int, timeout: int, emit) -> None:
    with open(ctx_path, encoding="utf-8") as fh:
        blob = json.load(fh)
    base_msgs = blob["messages"]
    msgs = base_msgs if spec.reasoning_replay else [
        {k: v for k, v in m.items() if k != "reasoning_content"} for m in base_msgs]

    prior_texts = [m.get("content") or "" for m in msgs if m.get("role") == "assistant"]
    prior_calls = {_canon_call(c["function"]["name"], c["function"]["arguments"])
                   for m in msgs if m.get("role") == "assistant"
                   for c in m.get("tool_calls") or []}

    body: dict = {"model": spec.model_id, "messages": msgs,
                  "max_tokens": max_tokens, "stream": False}
    if blob.get("tools_seen"):
        body["tools"] = _permissive_tools(blob["tools_seen"])

    ctx_name = os.path.basename(ctx_path)
    for i in range(n):
        row = {"model": spec.name, "provider": spec.provider, "context": ctx_name,
               "attempt": i, "reasoning_replay": spec.reasoning_replay,
               "ts": time.strftime("%H:%M:%S")}
        try:
            resp = _post(spec.base_url, key, body, timeout)
        except Exception as exc:  # noqa: BLE001 - surface any transport/HTTP error into the row
            detail = ""
            reader = getattr(exc, "read", None)
            if reader:
                try:
                    detail = reader()[:200].decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    pass
            row["error"] = f"{exc} {detail}".strip()
            emit(row)
            continue
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        content = (msg.get("content") or "").strip()
        calls = [(c["function"]["name"], c["function"]["arguments"])
                 for c in msg.get("tool_calls") or []]
        row.update({
            "finish": choice.get("finish_reason"),
            "closed": not calls,
            "repeat_text": any(content and p and content[:80] == p[:80] for p in prior_texts),
            "repeat_call": any(_canon_call(n2, a) in prior_calls for n2, a in calls),
            "text_head": content[:160],
            "calls": [(n2, a[:80]) for n2, a in calls],
        })
        emit(row)


def main() -> None:
    ap = argparse.ArgumentParser(description="Single-shot model x context grid.")
    ap.add_argument("--context", nargs="+", required=True, help="context JSON file(s)")
    ap.add_argument("--config", required=True, help="provider/model catalog JSON")
    ap.add_argument("--suite", nargs="+", required=True,
                    help="model or suite names from the catalog")
    ap.add_argument("--n", type=int, default=3, help="attempts per cell")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("-o", "--out", default="results.jsonl")
    args = ap.parse_args()

    catalog = Catalog.load(args.config)
    specs = catalog.resolve_suite(args.suite)

    with open(args.out, "a", encoding="utf-8") as fh:
        def emit(row: dict) -> None:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            summary = {k: row[k] for k in row if k != "text_head"}
            print(json.dumps(summary, ensure_ascii=False))
            sys.stdout.flush()

        for ctx in args.context:
            for spec in specs:
                print(f"### {spec.name} on {os.path.basename(ctx)}", file=sys.stderr)
                try:
                    key = catalog.api_key(spec)
                except RuntimeError as exc:
                    emit({"model": spec.name, "provider": spec.provider,
                          "context": os.path.basename(ctx), "attempt": 0,
                          "error": str(exc)})
                    continue
                run_cell(spec, key, ctx, args.n, args.max_tokens, args.timeout, emit)


if __name__ == "__main__":
    main()
