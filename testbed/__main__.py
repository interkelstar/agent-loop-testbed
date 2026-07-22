"""Unified CLI: ``python -m testbed <command> ...``

Commands:
  reconstruct   recording -> replayable context JSON (with optional cut)
  run           single-shot model x context grid -> results.jsonl
  drive         drive one model through a full simulated loop
  report        results.jsonl -> local HTML
  gen-samples   write the built-in synthetic sample contexts
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    cmd = sys.argv[1]
    sys.argv = [f"testbed {cmd}", *sys.argv[2:]]
    if cmd == "reconstruct":
        from .reconstruct import main as run
    elif cmd == "run":
        from .run import main as run
    elif cmd == "drive":
        from .driver import main as run
    elif cmd == "report":
        from .report import main as run
    elif cmd in ("gen-samples", "samples"):
        from .samples import main as run
    else:
        print(f"unknown command: {cmd}\n{__doc__}")
        raise SystemExit(2)
    run()


if __name__ == "__main__":
    main()
