"""Renders assets/hydradb-memory.html: what Engram's memory holds about
a repo ingested with fetch_github.py. Pure stdlib, reads the fact log
and session files, emits one self-contained page."""

import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

OUT = Path("assets/hydradb-memory.html")

LIGHT = {"issue": "#2a78d6", "pr": "#eb6834"}
DARK = {"issue": "#3987e5", "pr": "#d95926"}


def load():
    facts = Counter()
    for line in Path("data/.facts.jsonl").read_text().splitlines():
        if line:
            r = json.loads(line)
            if r["session_id"].startswith("gh-"):
                facts[r["session_id"]] += 1

    authors = defaultdict(lambda: {"issue": 0, "pr": 0})
    kinds = {}
    for p in sorted(Path("data/github_sessions").glob("*.json")):
        s = json.loads(p.read_text())
        kind = "pr" if "-pr-" in s["id"] else "issue"
        kinds[s["id"]] = kind
        m = re.match(r"(\S+) opened", s["turns"][0]["content"])
        authors[m.group(1) if m else "?"][kind] += 1
    return facts, authors, kinds


def rrect(x, y, w, h, r):
    # rectangle rounded on the data end (right) only
    if w <= r:
        return f'M{x},{y} h{w} v{h} h-{w} z'
    return (f'M{x},{y} h{w - r} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r} '
            f'a{r},{r} 0 0 1 -{r},{r} h-{w - r} z')


def bars_authors(authors, width=560, row=30):
    rows = sorted(authors.items(), key=lambda kv: -(kv[1]["issue"] + kv[1]["pr"]))
    peak = max(v["issue"] + v["pr"] for _, v in rows)
    scale = (width - 150) / peak
    parts, y = [], 4
    for name, v in rows:
        x = 140
        total = v["issue"] + v["pr"]
        parts.append(f'<text x="132" y="{y + 15}" text-anchor="end" class="lbl">{escape(name)}</text>')
        for kind in ("issue", "pr"):
            n = v[kind]
            if not n:
                continue
            w = max(n * scale - 2, 3)
            last = kind == "pr" or v["pr"] == 0
            shape = rrect(x, y + 4, w, 14, 4) if last else f'M{x},{y + 4} h{w} v14 h-{w} z'
            parts.append(f'<path d="{shape}" class="s-{kind}" data-tip="{escape(name)}: {n} {kind}{"s" if n > 1 else ""}"/>')
            x += n * scale
        parts.append(f'<text x="{x + 6}" y="{y + 15}" class="val">{total}</text>')
        y += row
    return "\n".join(parts), y + 4


def bars_facts(facts, kinds, width=560, row=24):
    rows = sorted(facts.items(), key=lambda kv: -kv[1])
    scale = (width - 150) / rows[0][1]
    parts, y = [], 4
    for sid, n in rows:
        kind = kinds.get(sid, "issue")
        label = sid.replace("gh-", "").replace("-", " #", 1).replace("pr", "PR").replace("issue", "issue")
        w = max(n * scale - 2, 3)
        parts.append(f'<text x="132" y="{y + 13}" text-anchor="end" class="lbl">{escape(label)}</text>')
        parts.append(f'<path d="{rrect(140, y + 3, w, 12, 4)}" class="s-{kind}" data-tip="{escape(sid)}: {n} facts"/>')
        parts.append(f'<text x="{140 + w + 8}" y="{y + 13}" class="val">{n}</text>')
        y += row
    return "\n".join(parts), y + 4


def main():
    facts, authors, kinds = load()
    a_svg, a_h = bars_authors(authors)
    f_svg, f_h = bars_facts(facts, kinds)
    n_threads, n_facts, n_people = len(facts), sum(facts.values()), len(authors)
    prs = sum(1 for k in kinds.values() if k == "pr")

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>engram memory: hydra-db/hydradb</title>
<style>
.viz-root {{
  color-scheme: light;
  --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --grid: #e8e7e3;
  --issue: {LIGHT["issue"]}; --pr: {LIGHT["pr"]};
}}
@media (prefers-color-scheme: dark) {{
  .viz-root {{
    color-scheme: dark;
    --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --grid: #33322f;
    --issue: {DARK["issue"]}; --pr: {DARK["pr"]};
  }}
}}
body {{ margin: 0; background: var(--surface); }}
.viz-root {{ max-width: 780px; margin: 0 auto; padding: 36px 20px 48px;
  background: var(--surface); color: var(--ink);
  font: 14px/1.45 system-ui, sans-serif; }}
h1 {{ font-size: 19px; margin: 0 0 2px; }}
.sub {{ color: var(--ink-2); margin: 0 0 22px; }}
.stats {{ display: flex; gap: 34px; margin: 0 0 30px; }}
.stats b {{ display: block; font-size: 26px; font-weight: 650; }}
.stats span {{ color: var(--ink-2); font-size: 13px; }}
h2 {{ font-size: 14px; font-weight: 600; margin: 26px 0 4px; }}
.legend {{ display: flex; gap: 18px; color: var(--ink-2); font-size: 12.5px; margin: 0 0 8px; }}
.legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; }}
.s-issue {{ fill: var(--issue); }} .s-pr {{ fill: var(--pr); }}
.lbl {{ fill: var(--ink-2); font-size: 12px; }}
.val {{ fill: var(--ink-2); font-size: 11.5px; }}
svg {{ display: block; }}
path[data-tip]:hover {{ opacity: .82; }}
#tip {{ position: fixed; display: none; background: var(--ink); color: var(--surface);
  padding: 5px 9px; border-radius: 6px; font-size: 12.5px; pointer-events: none; z-index: 9; }}
details {{ margin-top: 26px; color: var(--ink-2); }}
table {{ border-collapse: collapse; margin-top: 8px; }}
td, th {{ border-bottom: 1px solid var(--grid); padding: 4px 14px 4px 0; text-align: left; font-size: 12.5px; }}
</style></head>
<body><div class="viz-root">
<h1>What Engram remembers about hydra-db/hydradb</h1>
<p class="sub">{n_facts} facts extracted from the {n_threads} most recently active threads, all currently open</p>

<div class="stats">
  <div><b>{n_facts}</b><span>facts in the graph</span></div>
  <div><b>{n_threads}</b><span>threads ({prs} PRs, {n_threads - prs} issues)</span></div>
  <div><b>{n_people}</b><span>contributors</span></div>
</div>

<h2>Threads opened per contributor</h2>
<div class="legend"><span><i style="background:var(--issue)"></i>issues</span><span><i style="background:var(--pr)"></i>pull requests</span></div>
<svg viewBox="0 0 700 {a_h}" width="100%" role="img" aria-label="threads opened per contributor">
{a_svg}
</svg>

<h2>Memory density: facts per thread</h2>
<svg viewBox="0 0 700 {f_h}" width="100%" role="img" aria-label="facts extracted per thread">
{f_svg}
</svg>

<details><summary>data as a table</summary>
<table><tr><th>contributor</th><th>issues</th><th>PRs</th></tr>
{"".join(f"<tr><td>{escape(k)}</td><td>{v['issue']}</td><td>{v['pr']}</td></tr>" for k, v in sorted(authors.items(), key=lambda kv: -(kv[1]['issue'] + kv[1]['pr'])))}
</table>
<table><tr><th>thread</th><th>facts</th></tr>
{"".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(facts.items(), key=lambda kv: -kv[1]))}
</table>
</details>

<div id="tip"></div>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el => {{
  el.addEventListener('mousemove', e => {{
    tip.textContent = el.dataset.tip;
    tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY - 30) + 'px';
  }});
  el.addEventListener('mouseleave', () => tip.style.display = 'none');
}});
</script>
</div></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"{OUT} ({n_facts} facts, {n_threads} threads, {n_people} contributors)")


if __name__ == "__main__":
    main()
