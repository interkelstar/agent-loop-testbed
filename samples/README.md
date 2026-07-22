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
  tool calls. Measures loop *entry* from a clean start.
- **benign_close.json** — a completed task where the model only needs to confirm.
  Measures spurious re-looping after success (rare, stochastic).
