"""Full simulated loop: drive a model through a whole tool loop with synthesized
tool results, to see whether it converges or spins.

Starting from a context, repeatedly: call model -> if it returns tool calls,
append the assistant turn (replaying reasoning_content) and a synthesized tool
result, then call again. Stops when the model answers without tool calls
("closed") or at --max-steps.

Tool results are synthesized by a small STATEFUL mini-filesystem (see
``fake_result``): edits actually persist, reads return real content, and
time-like commands return a fresh value each call — preserving the "result
changes every call" property that defeats result-hash loop detectors, without
gaslighting the model with an inconsistent world.

``--world inconsistent`` switches to deliberately contradictory canned results
(edit "succeeds" but reads show nothing changed) as an experimental condition —
in the production incidents behind this tool, loops started after exactly this
kind of world-feedback contradiction. Measured on one mid-tier model over a
70k-char saturated context: both conditions closed within 2-4 steps in 10/10
driven runs, while ~10% of single-shot reactions showed repeat/distrust
behavior — i.e. the contradiction condition alone did not reproduce unbounded
entry either. Ship your own numbers, not ours.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

from .providers import Catalog
from .run import _permissive_tools, _post


def new_fs() -> dict:
    """Per-run mini-filesystem seeding the paths the built-in samples mention."""
    return {"reports/summary.md": "corrected totals: 43 entries\n",
            "notes.txt": "project started\n"}


def inconsistent_result(name: str) -> str:
    """Deliberately contradictory canned results (the ``--world inconsistent``
    experimental condition): the world never reflects the model's actions."""
    if name == "exec":
        return "(no output)"
    if name == "read":
        return "(file contents unchanged since last read)"
    if name in ("edit", "write"):
        return "No changes made. The replacement text is identical to the original."
    return "(ok)"


def fake_result(name: str, arguments: str, fs: dict) -> str:
    """Synthesize a plausible, state-consistent tool result."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except json.JSONDecodeError:
        args = {}
    cmd = str(args.get("command", ""))
    if name == "exec":
        if "date +%S" in cmd:
            return str(int(time.time()) % 60).zfill(2)  # fresh every call
        if "date +%s" in cmd:
            return str(int(time.time()))  # fresh every call
        m = re.search(r'echo\s+\\?"?([^">]+?)\\?"?\s*(>>|>)\s*(\S+)', cmd)
        if m:
            text, op, path = m.group(1).strip(), m.group(2), m.group(3).strip()
            fs[path] = (fs.get(path, "") + text + "\n") if op == ">>" else (text + "\n")
            return ""
        m = re.search(r"\bcat\s+(\S+)", cmd)
        if m:
            path = m.group(1).strip()
            return fs[path] if path in fs else f"cat: {path}: No such file or directory"
        if cmd.strip().startswith("touch"):
            m = re.search(r"touch\s+(\S+)", cmd)
            if m:
                fs.setdefault(m.group(1).strip(), "")
            return ""
        if cmd.strip().startswith("ls"):
            return "\n".join(f"-rw-r--r-- 1 app app {len(v)} Mar 28 12:00 {k}"
                             for k, v in fs.items())
        if cmd.strip().startswith(("tail", "head", "grep")):
            body = "\n".join(fs.values())
            return body[-400:] if cmd.strip().startswith("tail") else body[:400]
        return ""
    if name == "read":
        path = str(args.get("path", ""))
        return fs[path] if path in fs else f"read error: {path} not found"
    if name in ("edit", "write"):
        path = str(args.get("path", ""))
        if "append" in args:
            fs[path] = fs.get(path, "") + str(args["append"]) + "\n"
            return f"Successfully appended to {path}"
        if "newText" in args:
            old = str(args.get("oldText", ""))
            if old and old in fs.get(path, ""):
                fs[path] = fs[path].replace(old, str(args["newText"]), 1)
            else:
                new = str(args["newText"])
                fs[path] = new if new.endswith("\n") else new + "\n"
            return "Successfully replaced 1 block(s)."
        if "text" in args or "content" in args:
            fs[path] = str(args.get("text") or args.get("content"))
            return f"Successfully wrote {path}"
        return "Successfully wrote file."
    return "(ok)"


def drive(spec, key, blob, *, max_steps, max_tokens, timeout, strip_reasoning,
          world="consistent"):
    fs = new_fs()
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
                         "content": (inconsistent_result(c["function"]["name"]) if world == "inconsistent"
                                     else fake_result(c["function"]["name"], c["function"]["arguments"], fs))})
    print(f"===== outcome: {outcome} after {step + 1} steps")
    return f"{outcome}@{step + 1}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Drive a model through a full simulated tool loop.")
    ap.add_argument("--context", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--suite", nargs="+", required=True,
                    help="model or suite names from the catalog (same as `run`)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--strip-reasoning", action="store_true",
                    help="drop reasoning_content on replay (A/B the reasoning-replay factor)")
    ap.add_argument("--world", choices=("consistent", "inconsistent"), default="consistent",
                    help="tool-result synthesis: stateful mini-FS vs deliberately contradictory")
    args = ap.parse_args()

    catalog = Catalog.load(args.config)
    specs = catalog.resolve_suite(args.suite)
    with open(args.context, encoding="utf-8") as fh:
        blob = json.load(fh)

    summary: list[tuple[str, list[str]]] = []
    for spec in specs:
        try:
            key = catalog.api_key(spec)
        except RuntimeError as exc:
            print(f"\n########## {spec.name}: SKIPPED — {exc}")
            summary.append((spec.name, ["skipped"]))
            continue
        outcomes = []
        for run in range(args.runs):
            print(f"\n########## RUN {run} — {spec.name} (start len={len(blob['messages'])}) ##########")
            outcomes.append(drive(spec, key, blob, max_steps=args.max_steps,
                                  max_tokens=args.max_tokens, timeout=args.timeout,
                                  strip_reasoning=args.strip_reasoning, world=args.world))
        summary.append((spec.name, outcomes))

    print("\n===== SUMMARY (outcome per run) =====")
    for name, outcomes in summary:
        print(f"{name:22s} {' | '.join(outcomes)}")


if __name__ == "__main__":
    main()
