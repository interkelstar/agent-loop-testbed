# Samples

Synthetic conversations that reproduce the loop failure modes. They contain no
personal data — they were authored from scratch, not scrubbed from real logs.

Regenerate with `python -m testbed gen-samples --out-dir samples`.

- **mono_loop_midstream.json** — the model is 15 calls into an unbroken run of
  an identical `exec date +%s` call (the result differs every call, so no
  result-hash detector fires). Measures loop *continuation*: does the model
  break out and answer, or issue the 16th identical call? Mid-tier models
  continue; stronger models break out.
- **mono_loop_entry.json** — a step instruction interleaving a fixed phrase with
  tool calls. Measures loop *entry* from a clean start. Honest caveat: in our
  own runs no tested model entered a loop from this one — keep it as a control,
  not as a demonstration.
- **benign_close.json** — a completed task where the model only needs to confirm.
  Measures spurious re-looping after success (rare, stochastic).
- **saturated_pressure.json** — a long (~70k chars, ~190 msgs, ~48 tool calls)
  synthetic history structurally matched to the real incident contexts: digest
  walls, tool cycles, user-correction cycles, small *resolved* identical-call
  wobbles — then one trivially simple final request. Measures entry *pressure*
  on a saturated context. What we measured on one mid-tier reasoning model:
  ~10% of single-shot reactions repeated a prior identical call (with visible
  distrust-of-tools reasoning — "every time I tried edit, the file was
  unstable…") instead of just doing the step; driven multi-step runs closed
  within 2–4 steps in both `--world consistent` and `--world inconsistent`
  conditions. Unbounded entry did **not** reproduce synthetically at either
  70k or 150k chars — a precursor probe, not a loop guarantee.
- **post_answer_amnesia.json** — the saturated context plus the real-incident
  tail: the model has *already answered* the final request, then issued one
  redundant no-op tool call ("No changes made. The line is already present.").
  The correct next reaction is a brief closure. Measured on one mid-tier
  reasoning model: **70% of reactions issued one more identical call** —
  roughly a third full amnesia ("the user asked me to add a line… let me read
  the file first", its own in-context answer ignored) and two thirds
  perseverative verification ("the line is already present, let me read to
  confirm"); only 30% closed cleanly. This is the sharpest probe in the set.
