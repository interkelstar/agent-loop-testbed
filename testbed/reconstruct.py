"""Turn a recorded conversation into an OpenAI-style message array to replay.

Two input adapters:

  openai    – a JSON file that already contains {"messages": [...]} (or a bare
              list) in OpenAI chat format. Passed through, optionally cut.
  openclaw  – an OpenClaw agent session .jsonl (one event per line, each with a
              nested ``message``). Assistant ``thinking`` parts become
              ``reasoning_content``; ``toolCall`` parts become ``tool_calls``;
              ``toolResult`` messages become ``{"role":"tool",...}``.

Cutting: ``--cut-index N`` keeps the first N messages; ``--cut-marker STR`` stops
right after the first message whose serialized form contains STR. Cutting lets
you place the model at a chosen point in the conversation (e.g. right after a
tool result, so the next model call is the one under test).
"""

from __future__ import annotations

import argparse
import json
import sys


def _stringify(value) -> str:
    if value is None or isinstance(value, (str, int, float, bool)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_stringify(v) for v in value) + "]"
    keys = sorted(value.keys())
    return "{" + ",".join(f"{json.dumps(k)}:{_stringify(value[k])}" for k in keys) + "}"


def _parts(msg: dict) -> list:
    c = msg.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [p for p in (c or []) if isinstance(p, dict)]


def from_openclaw(lines) -> dict:
    out: list[dict] = []
    tools_seen: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = obj.get("data", obj)
        msg = data.get("message") if isinstance(data, dict) else None
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "user":
            text = "\n".join(p.get("text", "") for p in _parts(msg) if p.get("type") == "text")
            out.append({"role": "user", "content": text})
        elif role == "assistant":
            texts, thinks, calls = [], [], []
            for p in _parts(msg):
                t = p.get("type")
                if t == "text" and p.get("text", "").strip():
                    texts.append(p["text"])
                elif t == "thinking" and str(p.get("thinking", "")).strip():
                    thinks.append(str(p["thinking"]))
                elif t == "toolCall":
                    args = p.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    calls.append({"id": p.get("id"), "type": "function",
                                  "function": {"name": p.get("name"), "arguments": args}})
                    tools_seen.add(p.get("name"))
            am: dict = {"role": "assistant", "content": "\n".join(texts) if texts else None}
            if thinks:
                am["reasoning_content"] = "\n".join(thinks)
            if calls:
                am["tool_calls"] = calls
            if am["content"] is None and not calls and not thinks:
                continue
            out.append(am)
        elif role == "toolResult":
            text = "\n".join(p.get("text", "") for p in _parts(msg) if p.get("type") == "text")
            out.append({"role": "tool", "tool_call_id": msg.get("toolCallId"), "content": text})
    return {"messages": out, "tools_seen": sorted(t for t in tools_seen if t)}


def from_openai(text: str) -> dict:
    obj = json.loads(text)
    messages = obj["messages"] if isinstance(obj, dict) and "messages" in obj else obj
    tools = set()
    for m in messages:
        for c in m.get("tool_calls") or []:
            name = (c.get("function") or {}).get("name")
            if name:
                tools.add(name)
    seen = obj.get("tools_seen") if isinstance(obj, dict) else None
    return {"messages": messages, "tools_seen": seen or sorted(tools)}


def cut(blob: dict, *, index: int | None, marker: str | None) -> dict:
    msgs = blob["messages"]
    if index is not None:
        msgs = msgs[:index]
    elif marker is not None:
        kept = []
        for m in msgs:
            kept.append(m)
            if marker in json.dumps(m, ensure_ascii=False):
                break
        msgs = kept
    return {"messages": msgs, "tools_seen": blob.get("tools_seen", [])}


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconstruct an OpenAI message array from a recording.")
    ap.add_argument("input")
    ap.add_argument("--adapter", choices=["openclaw", "openai"], default="openai")
    ap.add_argument("--cut-index", type=int)
    ap.add_argument("--cut-marker")
    ap.add_argument("-o", "--out", default="context.json")
    args = ap.parse_args()

    if args.adapter == "openclaw":
        with open(args.input, encoding="utf-8") as fh:
            blob = from_openclaw(fh)
    else:
        with open(args.input, encoding="utf-8") as fh:
            blob = from_openai(fh.read())

    blob = cut(blob, index=args.cut_index, marker=args.cut_marker)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, indent=1)
    roles = [m["role"] for m in blob["messages"]]
    print(f"{args.out}: {len(blob['messages'])} messages; tail={roles[-6:]}; "
          f"tools={blob['tools_seen']}", file=sys.stderr)


if __name__ == "__main__":
    main()
