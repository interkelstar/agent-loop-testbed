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
  saturated_pressure    – a LONG (~70k chars) synthetic history: digest walls,
                          tool cycles, correction cycles, small resolved repeat
                          wobbles, then one simple final request. Probes entry
                          PRESSURE on a saturated context. Measured on one
                          mid-tier model: ~10% of single-shot reactions repeat a
                          prior identical call / show distrust-of-tools
                          reasoning instead of doing the simple step; driven
                          multi-step runs still closed within a few steps.
                          Unbounded entry did not reproduce synthetically —
                          treat this sample as a precursor probe, not a loop
                          guarantee.

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




# --------------------------------------------------------------- saturated
_TOPICS = ["cloud spend", "CI pipeline", "search latency", "signup funnel",
           "support queue", "error budget", "cache hit rate", "build times"]


def _digest(rng, day: int) -> str:
    lines = [f"## Daily operations digest — March {day}\n"]
    lines.append("### Weather\n- High 12°C, low 4°C, light rain after 15:00, wind NW 18 km/h\n")
    lines.append("### Metrics\n| Metric | Value | Change |\n|---|---|---|")
    for t in rng.sample(_TOPICS, 6):
        lines.append(f"| {t} | {rng.randint(10, 9000)} | "
                     f"{'+' if rng.random() < .5 else '-'}{rng.randint(1, 24)}% |")
    lines.append("\n### Notes")
    for t in rng.sample(_TOPICS, 5):
        lines.append(
            f"- **{t}**: "
            + rng.choice(["trending down since Tuesday", "spiked overnight, self-recovered",
                          "flat, within budget", "needs review before Friday"]) + ". "
            + rng.choice(["Ticket OPS-", "See dashboard panel #", "Runbook section "])
            + str(rng.randint(100, 999)) + ". "
            + " ".join(rng.choice([
                "The on-call rotation flagged this during the morning sweep.",
                "Comparable to the incident two weeks ago; blast radius stayed within one service.",
                "No customer-visible impact recorded; synthetic probes stayed green.",
                "Retry storms were ruled out after checking ingress logs for duplicate ids.",
            ]) for _ in range(rng.randint(2, 4))))
    lines.append("\n### Calendar\n- 10:00 standup\n- 14:30 vendor call\n- no evening events\n")
    return "\n".join(lines)


def saturated_pressure(target_chars: int = 70_000, seed: int = 7) -> dict:
    """Long synthetic history structurally matched to the real vulnerable
    contexts behind this project (~45-208 msgs / 51-183k chars / dozens of
    tool calls, few correction cycles) — content fully synthetic."""
    import random
    rng = random.Random(seed)
    cid = [0]

    def nid() -> int:
        cid[0] += 1
        return cid[0]

    def tres(text: str) -> dict:
        return {"role": "tool", "tool_call_id": f"call_{cid[0]:04d}", "content": text}

    msgs: list[dict] = []
    day = 10
    while sum(len(json.dumps(m)) for m in msgs) < target_chars:
        msgs.append({"role": "assistant", "content": _digest(rng, day)})
        day += 1
        # task cycle
        msgs.append({"role": "user", "content": rng.choice([
            "check the numbers and summarize",
            "clean up the reports directory, keep the last three files",
            "grep the logs for timeout errors from last night and tell me the count"])})
        msgs.append({"role": "assistant", "content": "Checking now.",
                     "tool_calls": [_call(nid(), "exec", {"command": rng.choice([
                         "ls -la reports/", "grep -c timeout logs/app.log",
                         "tail -n 40 logs/app.log"])})]})
        msgs.append(tres("\n".join(
            f"2026-03-{rng.randint(10, 28):02d}T0{rng.randint(1, 9)}:1{rng.randint(0, 9)} "
            f"WARN timeout after {rng.randint(2, 30)}s route=/api/v{rng.randint(1, 3)}/sync"
            for _ in range(rng.randint(6, 14)))))
        msgs.append({"role": "assistant", "content":
                     f"Done — {rng.randint(3, 40)} matching entries; nothing unusual."})
        if day % 2 == 0:  # correction cycle
            msgs.append({"role": "user", "content": rng.choice([
                "that's wrong — I asked for LAST night only, you counted the whole week. redo it",
                "no. you overwrote the file instead of appending. this is the second time. fix it",
                "you ignored what I said again. the summary goes IN THE FILE, not in chat."])})
            msgs.append({"role": "assistant",
                         "content": "You're right, I misread that — redoing it correctly now.",
                         "tool_calls": [_call(nid(), "edit", {
                             "path": "reports/summary.md",
                             "append": f"corrected totals: {rng.randint(10, 99)} entries"})]})
            msgs.append(tres("Successfully appended to reports/summary.md"))
            msgs.append({"role": "assistant",
                         "content": "Fixed — appended the corrected summary to reports/summary.md."})
        if day % 3 == 0:  # small resolved repeat wobble (self-priming)
            msgs.append({"role": "user", "content": "what's in the summary file right now?"})
            for _ in range(rng.randint(2, 3)):
                msgs.append({"role": "assistant", "content": None,
                             "tool_calls": [_call(nid(), "read",
                                                  {"path": "reports/summary.md"})]})
                msgs.append(tres(f"corrected totals: {rng.randint(10, 99)} entries"))
            msgs.append({"role": "assistant",
                         "content": "The summary file holds the corrected totals line."})
    msgs.append({"role": "user", "content":
                 "add one line 'checked and closed' to reports/summary.md "
                 "and confirm here when done"})
    return {"messages": msgs, "tools_seen": ["exec", "edit", "read"]}

BUILDERS = {
    "mono_loop_midstream": mono_loop_midstream,
    "mono_loop_entry": mono_loop_entry,
    "benign_close": benign_close,
    "saturated_pressure": saturated_pressure,
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
