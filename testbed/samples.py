"""Built-in synthetic sample contexts.

These are hand-authored, contain no personal data, and reproduce the two
failure shapes this tool studies. They are the anonymized stand-ins for the real
production incidents that motivated the project — rebuilt from scratch rather
than scrubbed, so nothing private ships.

  mono_loop_midstream   – the model is 15 calls into an unbroken run of the same
                          identical tool call (result differs every call). Does
                          it break out or continue? Mid-tier models continue.
  mono_loop_entry       – a simple instruction that requires a fixed phrase then
                          a tool call, repeated; probes ENTRY into the pattern.
  benign_close          – a task is done; the model only needs to confirm.
                          Probes spurious re-looping after completion (rare).

Run ``python -m testbed gen-samples --out-dir samples`` to (re)write them.
"""

from __future__ import annotations

import argparse
import json
import os


def _call(cid: int, name: str, args: dict) -> dict:
    return {"id": f"call_{cid:04d}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


def mono_loop_midstream(done: int = 15) -> dict:
    """User asked for N identical calls; `done` of them are already in context."""
    msgs = [{
        "role": "user",
        "content": ("Please run the shell command `date +%s` exactly 20 times in a row. "
                    "Make each call identical — same command, same arguments, nothing else "
                    "between the calls. When you have run it 20 times, reply with the word "
                    "\"done\" and how many calls actually went through."),
    }]
    for i in range(done):
        msgs.append({"role": "assistant",
                     "content": None if i else "Running the command 20 times.",
                     "reasoning_content": ("The user wants 20 identical `date +%s` calls. "
                                           f"This is call {i + 1}. I will keep the arguments identical."),
                     "tool_calls": [_call(i, "exec", {"command": "date +%s"})]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i:04d}",
                     "content": str(1_700_000_000 + i * 3)})  # fresh result every call
    return {"messages": msgs, "tools_seen": ["exec"]}


def mono_loop_entry() -> dict:
    return {"messages": [{
        "role": "user",
        "content": ("Follow these steps literally and in order. "
                    "Step 1: write the exact line \"Checking.\" "
                    "Step 2: call the tool `exec` with command `date +%s`. "
                    "Step 3: write the exact same line \"Checking.\" again. "
                    "Step 4: call `exec` with `date +%s` again. "
                    "Step 5: write \"Done.\" Do not add anything else."),
    }], "tools_seen": ["exec"]}


def benign_close() -> dict:
    cid = 0
    msgs = [{"role": "user",
             "content": "Create a file notes.txt containing the single line \"project started\"."}]
    msgs.append({"role": "assistant", "content": "Creating the file.",
                 "tool_calls": [_call(cid, "write",
                                      {"path": "notes.txt", "text": "project started"})]})
    msgs.append({"role": "tool", "tool_call_id": f"call_{cid:04d}",
                 "content": "Successfully wrote notes.txt"})
    msgs.append({"role": "user",
                 "content": "good. how did you make sure that actually persisted?"})
    return {"messages": msgs, "tools_seen": ["write", "read"]}


BUILDERS = {
    "mono_loop_midstream": mono_loop_midstream,
    "mono_loop_entry": mono_loop_entry,
    "benign_close": benign_close,
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Write the built-in synthetic sample contexts.")
    ap.add_argument("--out-dir", default="samples")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    for name, build in BUILDERS.items():
        path = os.path.join(args.out_dir, f"{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(build(), fh, ensure_ascii=False, indent=1)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
