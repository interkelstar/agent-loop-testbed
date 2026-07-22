"""Render a results.jsonl into a self-contained local HTML report.

One row per (model, context); attempts are fixed-size chips in numbered columns
so outcomes line up visually across models. Each row ends with a closed-x/n
summary; with several contexts a per-model "all files" total row is added.
Hover a chip for a preview of the model's reply. No external assets, no
network — open the file in any browser. Works in light and dark themes.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import OrderedDict

from .run import classify

GLYPH = {
    "closes": ("✓", "ok", "closed with a text answer"),
    "acts": ("→", "act", "called a new tool (did something not seen before)"),
    "repeat": ("⟳", "bad", "repeated a prior text / identical tool call"),
    "error": ("!", "mut", "API error"),
}

STYLE = """
:root{color-scheme:light;--s1:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
--mut:#898781;--grid:#e1e0d9;--border:rgba(11,11,11,.10);
--ok:#0b7c0b;--ok-bg:#e4f3e4;--bad:#c22f2f;--bad-bg:#fae5e5;--act:#2a6cc0;--act-bg:#e4edf8;--mut-bg:#eeeeea}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){color-scheme:dark;
--s1:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--border:rgba(255,255,255,.10);
--ok:#5fd05f;--ok-bg:#12300f;--bad:#f07272;--bad-bg:#3a1414;--act:#6aa9ec;--act-bg:#12253c;--mut:#8a887f;--mut-bg:#242422}}
:root[data-theme=dark]{color-scheme:dark;--s1:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;
--grid:#2c2c2a;--border:rgba(255,255,255,.10);
--ok:#5fd05f;--ok-bg:#12300f;--bad:#f07272;--bad-bg:#3a1414;--act:#6aa9ec;--act-bg:#12253c;--mut:#8a887f;--mut-bg:#242422}
body{background:var(--page);color:var(--ink);margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1160px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--ink2);margin:0 0 24px}
.tiles{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}
.tile{background:var(--s1);border:1px solid var(--border);border-radius:6px;padding:12px 16px;min-width:180px;flex:1}
.tile b{font-size:20px;font-variant-numeric:tabular-nums}.tile small{color:var(--ink2);display:block}
.wrap{overflow-x:auto;background:var(--s1);border:1px solid var(--border);border-radius:6px}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--grid);padding:7px 8px;text-align:left;vertical-align:middle;white-space:nowrap}
th.att,td.att{text-align:center;padding:7px 3px;width:30px}
th.att{font-size:12px;color:var(--ink2);font-weight:600}
th.model{white-space:nowrap}.serving{display:block;color:var(--mut);font-size:11.5px;font-weight:400}
td.ctx{color:var(--ink2);font-size:12.5px;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.chip{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;
border-radius:5px;font-size:13.5px;font-weight:700;cursor:default}
.chip.ok{color:var(--ok);background:var(--ok-bg)}
.chip.bad{color:var(--bad);background:var(--bad-bg)}
.chip.act{color:var(--act);background:var(--act-bg)}
.chip.mut{color:var(--mut);background:var(--mut-bg)}
td.sum{font-variant-numeric:tabular-nums;text-align:right;font-weight:600}
td.sum small{color:var(--ink2);font-weight:400;margin-left:6px}
tr.total th,tr.total td{border-top:2px solid var(--grid);background:color-mix(in srgb,var(--grid) 22%,transparent)}
tr.total th{font-weight:700}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:14px 2px 0;color:var(--ink2);font-size:13px;align-items:center}
.legend .chip{margin-right:5px}
.note{color:var(--mut);font-size:12.5px;margin-top:18px;max-width:78ch}
"""


def _order(rows, key):
    seen = OrderedDict()
    for r in rows:
        seen.setdefault(key(r), None)
    return list(seen.keys())


def _chip(row) -> str:
    if row.get("mode") == "drive":
        cls = {"closed": "ok", "max-steps": "bad"}.get(row.get("outcome"), "mut")
        lab = f"{row.get('outcome')} after {row.get('steps')} steps ({row.get('world', '')} world)"
        return (f'<span class="chip {cls}" title="{html.escape(lab)}">'
                f"{row.get('steps', '?')}</span>")
    g, cls, lab = GLYPH[classify(row)]
    tip = (row.get("text_head")
           or "; ".join(f"{n}({a})" for n, a in row.get("calls", []))
           or row.get("error", ""))
    return (f'<span class="chip {cls}" '
            f'title="{html.escape(lab)}: {html.escape(str(tip)[:220])}">{g}</span>')


def _summary(rs) -> str:
    valid = [r for r in rs if classify(r) != "error"]
    closed = sum(1 for r in valid if classify(r) == "closes")
    pct = f"{round(100 * closed / len(valid))}%" if valid else "–"
    return f'<td class="sum">{closed}/{len(valid)}<small>{pct} closed</small></td>'


def build(rows: list[dict], title: str) -> str:
    # dedup: keep the last row per (model, context, attempt)
    dd: OrderedDict = OrderedDict()
    for r in rows:
        dd[(r["model"], r.get("provider", ""), r["context"], r.get("attempt", 0))] = r
    rows = list(dd.values())

    contexts = _order(rows, lambda r: r["context"])
    models = _order(rows, lambda r: (r["model"], r.get("provider", "")))
    by_cell: dict = {}
    for r in rows:
        by_cell.setdefault((r["model"], r["context"]), []).append(r)
    max_n = max((len(v) for v in by_cell.values()), default=0)

    multi = len(contexts) > 1
    att_head = "".join(f'<th class="att">{i + 1}</th>' for i in range(max_n))
    ctx_col = "<th>file</th>" if multi else ""
    thead = f'<tr><th>model</th>{ctx_col}{att_head}<th style="text-align:right">closed</th></tr>'

    body = []
    for model, prov in models:
        serving = f'<span class="serving">{html.escape(prov)}</span>' if prov else ""
        model_rows_all = []
        first = True
        for ctx in contexts:
            rs = sorted(by_cell.get((model, ctx), []), key=lambda r: r.get("attempt", 0))
            if not rs:
                continue
            model_rows_all.extend(rs)
            cells = "".join(f'<td class="att">{_chip(r)}</td>' for r in rs)
            cells += f'<td class="att"></td>' * (max_n - len(rs))
            mcell = (f'<th class="model">{html.escape(model)}{serving}</th>'
                     if first else '<th class="model"></th>')
            ccell = f'<td class="ctx" title="{html.escape(ctx)}">{html.escape(ctx)}</td>' if multi else ""
            body.append(f"<tr>{mcell}{ccell}{cells}{_summary(rs)}</tr>")
            first = False
        if multi and len([c for c in contexts if by_cell.get((model, c))]) > 1:
            span = max_n
            body.append(f'<tr class="total"><th class="model">{html.escape(model)}</th>'
                        f'<td class="ctx">all files</td><td class="att" colspan="{span}"></td>'
                        f"{_summary(model_rows_all)}</tr>")

    drive_mode = bool(rows and rows[0].get("mode") == "drive")
    if drive_mode:
        valid = [r for r in rows if r.get("outcome") != "api-error"]
        n_ok = sum(1 for r in valid if r.get("outcome") == "closed")
        tiles = [
            (f"{n_ok}/{len(valid)}", "driven runs that reached a text answer"),
            (f"{max((r['steps'] for r in valid), default=0)}", "worst-case steps to converge"),
            (str(len(models)), f"models × {len(contexts)} context file(s)"),
        ]
    else:
        valid = [r for r in rows if classify(r) != "error"]
        n_repeat = sum(1 for r in valid if classify(r) == "repeat")
        n_closes = sum(1 for r in valid if classify(r) == "closes")
        tiles = [
            (f"{n_closes}/{len(valid)}", "attempts that closed with a text answer (the correct outcome)"),
            (f"{n_repeat}/{len(valid)}", "attempts that repeated a prior text or identical tool call"),
            (str(len(models)), f"models × {len(contexts)} context file(s)"),
        ]
    tile_html = "".join(
        f'<div class="tile"><b>{html.escape(v)}</b><small>{html.escape(d)}</small></div>'
        for v, d in tiles)

    legend = "".join(
        f'<span><span class="chip {cls}">{g}</span><b>{name}</b></span>'
        for g, cls, name in [
            (GLYPH["closes"][0], "ok", "closed"),
            (GLYPH["acts"][0], "act", "acted"),
            (GLYPH["repeat"][0], "bad", "repeat"),
            (GLYPH["error"][0], "mut", "error"),
        ])

    return (
        f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
        f"<style>{STYLE}</style><main>"
        f"<h1>{html.escape(title)}</h1>"
        f'<p class="sub">One chip per attempt/run, in order. Single-shot chips show outcome '
        f"glyphs; driven-run chips show the number of steps to converge. Hover for details.</p>"
        f'<div class="tiles">{tile_html}</div>'
        f'<div class="wrap"><table><thead>{thead}</thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
        f'<div class="legend">{legend}</div>'
        f'<p class="note">Single-shot chips show the model’s FIRST reaction to the context; '
        f"run <code>drive</code> for a full loop. A ⟳ means the reply duplicates something "
        f"already in the conversation (verbatim text, or an identical tool call — arguments "
        f"compared as canonical JSON). Source: results.jsonl.</p>"
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
