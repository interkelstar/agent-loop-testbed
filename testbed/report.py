"""Render a results.jsonl into a self-contained local HTML report.

Rows are models, columns are contexts, both derived from the data (in first-seen
order). One glyph per attempt; hover a glyph for a preview of the model's reply.
No external assets, no network — open the file in any browser. Works in light
and dark themes.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import OrderedDict

from .run import classify

GLYPH = {
    "closes": ("✓", "var(--ok)", "closed with a text answer"),
    "acts": ("→", "var(--act)", "called a new tool (progress)"),
    "repeat": ("⟳", "var(--bad)", "repeated a prior text/tool call"),
    "error": ("⚠", "var(--mut)", "API error"),
}

STYLE = """
:root{color-scheme:light;--s1:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
--mut:#898781;--grid:#e1e0d9;--border:rgba(11,11,11,.10);--ok:#0ca30c;--bad:#d03b3b;--act:#2a78d6}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){color-scheme:dark;
--s1:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--act:#3987e5}}
:root[data-theme=dark]{color-scheme:dark;--s1:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;
--grid:#2c2c2a;--border:rgba(255,255,255,.10);--act:#3987e5}
body{background:var(--page);color:var(--ink);margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--ink2);margin:0 0 24px}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}
.tile{background:var(--s1);border:1px solid var(--border);border-radius:6px;padding:12px 16px;min-width:180px;flex:1}
.tile b{font-size:20px;font-variant-numeric:tabular-nums}.tile small{color:var(--ink2);display:block}
.wrap{overflow-x:auto;background:var(--s1);border:1px solid var(--border);border-radius:6px}
table{border-collapse:collapse;width:100%;min-width:720px}
th,td{border-bottom:1px solid var(--grid);padding:8px 10px;text-align:left;vertical-align:top}
th.ctx{font-size:12.5px;font-weight:600}
th.model{white-space:nowrap}.serving{display:block;color:var(--mut);font-size:11.5px}
.dot{font-size:17px;margin-right:6px;cursor:default}
.legend{display:flex;gap:18px;flex-wrap:wrap;margin:14px 2px 0;color:var(--ink2);font-size:13px}
.note{color:var(--mut);font-size:12.5px;margin-top:18px;max-width:70ch}
"""


def _order(rows, key):
    seen = OrderedDict()
    for r in rows:
        seen.setdefault(key(r), None)
    return list(seen.keys())


def build(rows: list[dict], title: str) -> str:
    contexts = _order(rows, lambda r: r["context"])
    models = _order(rows, lambda r: (r["model"], r.get("provider", "")))
    by_cell: dict = {}
    for r in rows:
        by_cell.setdefault((r["model"], r["context"]), []).append(r)

    def cell(model, ctx):
        rs = sorted(by_cell.get((model, ctx), []), key=lambda r: r.get("attempt", 0))
        if not rs:
            return '<td class="mut">·</td>'
        dots = []
        for r in rs:
            g, col, lab = GLYPH[classify(r)]
            tip = (r.get("text_head")
                   or "; ".join(f"{n}({a})" for n, a in r.get("calls", []))
                   or r.get("error", ""))
            dots.append(f'<span class="dot" style="color:{col}" '
                        f'title="{html.escape(lab)}: {html.escape(str(tip)[:220])}">{g}</span>')
        return f"<td>{''.join(dots)}</td>"

    thead = "".join(f'<th class="ctx">{html.escape(c)}</th>' for c in contexts)
    body = []
    for model, prov in models:
        tds = "".join(cell(model, c) for c in contexts)
        serving = f'<span class="serving">{html.escape(prov)}</span>' if prov else ""
        body.append(f'<tr><th class="model">{html.escape(model)}{serving}</th>{tds}</tr>')

    valid = [r for r in rows if classify(r) != "error"]
    n_repeat = sum(1 for r in valid if classify(r) == "repeat")
    n_closes = sum(1 for r in valid if classify(r) == "closes")
    tiles = [
        (f"{n_repeat}/{len(valid)}", "attempts that repeated a prior text or tool call (loop signal)"),
        (f"{n_closes}/{len(valid)}", "attempts that closed with a text answer"),
        (str(len(models)), "models × " + str(len(contexts)) + " contexts"),
    ]
    tile_html = "".join(
        f'<div class="tile"><b>{html.escape(v)}</b><small>{html.escape(d)}</small></div>'
        for v, d in tiles)

    legend = "".join(
        f'<span style="color:{col}">{g} <b>{lab}</b></span>'
        for g, col, lab in [
            (GLYPH["closes"][0], GLYPH["closes"][1], "closed"),
            (GLYPH["acts"][0], GLYPH["acts"][1], "acted"),
            (GLYPH["repeat"][0], GLYPH["repeat"][1], "repeat"),
            (GLYPH["error"][0], GLYPH["error"][1], "error"),
        ])

    return (
        f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
        f"<style>{STYLE}</style><main>"
        f"<h1>{html.escape(title)}</h1>"
        f'<p class="sub">One glyph per attempt. Each cell is a model’s reaction to a '
        f"recorded conversation, replayed single-shot. Hover a glyph for a reply preview.</p>"
        f'<div class="tiles">{tile_html}</div>'
        f'<div class="wrap"><table><thead><tr><th>model</th>{thead}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
        f'<div class="legend">{legend}</div>'
        f'<p class="note">Single-shot cells show the model’s FIRST reaction to the context; '
        f"run the driver for a full loop. A ⟳ means the reply duplicates something already "
        f"in the conversation (verbatim text, or an identical tool call). Source: results.jsonl.</p>"
        f"</main>")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render results.jsonl to a local HTML report.")
    ap.add_argument("results")
    ap.add_argument("-o", "--out", default="report.html")
    ap.add_argument("--title", default="Agent Loop Testbed — results")
    args = ap.parse_args()
    with open(args.results, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(build(rows, args.title))
    print(f"wrote {args.out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
