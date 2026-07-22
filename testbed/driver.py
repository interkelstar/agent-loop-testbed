"""Full simulated loop: drive a model through a whole tool loop with synthesized
tool results, to see whether it converges or spins.

Starting from a context, repeatedly: call model -> if it returns tool calls,
append the assistant turn (replaying reasoning_content) and a synthesized tool
result, then call again. Stops when the model answers without tool calls
("closed") or at --max-steps.

Tool results are synthesized by a small table (see ``fake_result``); crucially,
time-like commands return a fresh value each call, preserving the "result
changes every call" property that defeats result-hash loop detectors.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

from .providers import Catalog
from .run import _permissive_tools, _post


def fake_result(name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except json.JSONDecodeError:
        args = {}
    cmd = str(args.get("command", ""))
    if name == "exec" and ("date +%s" in cmd or "date +%S" in cmd):
        return str(int(time.time()) % 60).zfill(2)  # fresh every call
    if name == "exec":
        return "(no output)"
    if name == "read":
        return "(file contents unchanged since last read)"
    if name in ("edit", "write"):
        return "No changes made. The replacement text is identical to the original."
    return "(ok)"


def drive(spec, key, blob, *, max_steps, max_tokens, timeout, strip_reasoning):
    msgs = [dict(m) for m in blob["messages"]]
    if strip_reasoning:
        msgs = [{k: v for k, v in m.items() if k != "reasoning_content"} for m in msgs]
    seen_texts = [m.get("content") or "" for m in msgs if m.get("role") == "assistant"]
    seen_calls = [(c["function"]["name"], c["function"]["arguments"])
                  for m in msgs if m.get("role") == "assistant"
                  for c in m.get("tool_calls") or []]
    outcome, step = "max-steps", 0
    for step in range(max_steps):
        body = {"model": spec.model_id, "messages": msgs,
                "max_tokens": max_tokens, "stream": False}
        if blob.get("tools_seen"):
            body["tools"] = _permissive_tools(blob["tools_seen"])
        try:
            resp = _post(spec.base_url, key, body, timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"[{step}] REQUEST FAILED: {exc}")
            outcome = "api-error"
            break
        msg = (resp.get("choices") or [{}])[0].get("message", {})
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or "").strip()
        calls = msg.get("tool_calls") or []
        rep_t = any(content and p and content[:60] == p[:60] for p in seen_texts)
        rep_c = any((c["function"]["name"], c["function"]["arguments"]) in seen_calls for c in calls)
        names = [(c["function"]["name"], c["function"]["arguments"][:50]) for c in calls]
        print(f"[{step}] calls={names} repeat_text={rep_t} repeat_call={rep_c}")
        if reasoning:
            print(f"     think: {reasoning[:160]!r}")
        if content:
            print(f"     text : {content[:160]!r}")
        am = {"role": "assistant", "content": content or None}
        if reasoning and not strip_reasoning:
            am["reasoning_content"] = reasoning
        if calls:
            am["tool_calls"] = calls
        msgs.append(am)
        if content:
            seen_texts.append(content)
        if not calls:
            outcome = "closed"
            break
        for c in calls:
            seen_calls.append((c["function"]["name"], c["function"]["arguments"]))
            msgs.append({"role": "tool", "tool_call_id": c.get("id"),
                         "content": fake_result(c["function"]["name"], c["function"]["arguments"])})
    print(f"===== outcome: {outcome} after {step + 1} steps")
    return outcome


def main() -> None:
    ap = argparse.ArgumentParser(description="Drive a model through a full simulated tool loop.")
    ap.add_argument("--context", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--model", required=True, help="a model name from the catalog")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--strip-reasoning", action="store_true",
                    help="drop reasoning_content on replay (A/B the reasoning-replay factor)")
    args = ap.parse_args()

    catalog = Catalog.load(args.config)
    spec = catalog.resolve(args.model)
    key = catalog.api_key(spec)
    with open(args.context, encoding="utf-8") as fh:
        blob = json.load(fh)

    for run in range(args.runs):
        print(f"\n########## RUN {run} — {spec.name} (start len={len(blob['messages'])}) ##########")
        drive(spec, key, blob, max_steps=args.max_steps, max_tokens=args.max_tokens,
              timeout=args.timeout, strip_reasoning=args.strip_reasoning)


if __name__ == "__main__":
    main()
