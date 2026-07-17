"""Static dashboard generator -> docs/index.html (served by GitHub Pages).
Every displayed value is the source's verbatim text; absent fields say Not listed."""
import html
from pathlib import Path

from .filters import city_rank, comp_sort_value
from .models import norm

DOCS = Path(__file__).resolve().parent.parent / "docs"
TIER_ORDER = {"A": 0, "B": 1, "C": 2}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1a1a1a;--muted:#666;--line:#e2e2de;
--accent:#0c447c;--badge:#e6f1fb;--warn-bg:#faeeda;--warn-text:#633806;
--new:#1d9e75;--gone:#999}
@media(prefers-color-scheme:dark){:root{--bg:#171715;--card:#22221f;--text:#eee;
--muted:#9a9a94;--line:#3a3a36;--accent:#85b7eb;--badge:#0c2c4c;
--warn-bg:#3a2c10;--warn-text:#fac775}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);
color:var(--text);font:16px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:840px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:16px}
.warn{background:var(--warn-bg);color:var(--warn-text);border-radius:8px;
padding:10px 14px;font-size:14px;margin-bottom:16px}
h2{font-size:17px;margin:24px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:10px}
.co{font-weight:600}.badge{display:inline-block;font-size:11px;font-weight:600;
background:var(--badge);color:var(--accent);border-radius:4px;padding:1px 6px;
margin-left:6px;vertical-align:1px}
.badge.new{background:transparent;color:var(--new);border:1px solid var(--new)}
.title a{color:var(--accent);text-decoration:none;font-size:17px}
.title a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:13px;margin-top:4px}
.comp{font-size:14px;margin-top:4px}
details{margin-top:8px;font-size:14px}summary{cursor:pointer;color:var(--muted)}
details pre{white-space:pre-wrap;font:13px/1.5 inherit;color:var(--text);
max-height:400px;overflow-y:auto;background:none;margin:8px 0 0}
section details.fold>summary{font-size:15px;color:var(--text);font-weight:600}
.gone .title a{color:var(--gone)}.gone .co{color:var(--gone)}
footer{color:var(--muted);font-size:12px;margin:24px 0}
.on{color:var(--text)}.off{color:var(--muted);opacity:.65}
"""


def esc(s):
    return html.escape(str(s)) if s else ""


def _card(j, prestige):
    tier_badge = f'<span class="badge">Tier {esc(prestige)}</span>' if prestige else ""
    new_badge = '<span class="badge new">new</span>' if "new" in j["flags"] else ""
    lp = ' <span class="badge">long-posted</span>' if "long-posted" in j["flags"] else ""
    comp = esc(j.get("comp")) or '<span style="color:var(--muted)">Not listed</span>'
    posted = esc(j.get("posted_date")) or "Not listed"
    loc = esc(j.get("location")) or "Not listed"
    desc = ""
    if j.get("description"):
        desc = f"<details><summary>Job description</summary><pre>{esc(j['description'])}</pre></details>"
    gone = ""
    if j["status"] == "gone":
        gone = f' — no longer listed as of {esc(j["gone_date"])}'
    return f"""<div class="card{' gone' if j['status'] == 'gone' else ''}">
<div class="co">{esc(j['company'])}{tier_badge}{new_badge}{lp}</div>
<div class="title"><a href="{esc(j['url'])}" target="_blank" rel="noopener">{esc(j['title'])}</a></div>
<div class="meta">{loc} &middot; Posted: {posted}{gone}</div>
<div class="comp">Comp: {comp}</div>
{desc}</div>"""


def generate(store, companies, cities, warnings, today):
    prestige = {norm(c["name"]): c["tier"] for c in companies}

    def p_of(j):
        return prestige.get(norm(j["company"]))

    def sort_key(j):
        p = p_of(j)
        return (TIER_ORDER.get(p, 3), -comp_sort_value(j.get("comp")),
                city_rank(j.get("location"), cities), norm(j["company"]))

    active = [j for j in store.values() if j["status"] == "active"]
    t1_direct = sorted((j for j in active if j["tier"] == 1 and j["kind"] == "direct"),
                       key=sort_key)
    t2_direct = sorted((j for j in active if j["tier"] == 2 and j["kind"] == "direct"),
                       key=sort_key)
    boards = sorted((j for j in active if j["kind"] == "board"), key=sort_key)
    gone = sorted((j for j in store.values() if j["status"] == "gone"),
                  key=lambda j: j.get("gone_date") or "", reverse=True)[:25]

    warn_html = ""
    if warnings:
        items = "<br>".join(esc(w) for w in warnings)
        warn_html = f'<div class="warn">&#9888; Source health: {items}</div>'

    def section(title, jobs, fold=False):
        if not jobs:
            return ""
        cards = "\n".join(_card(j, p_of(j)) for j in jobs)
        if fold:
            return (f'<section><details class="fold"><summary>{esc(title)} '
                    f'({len(jobs)})</summary>{cards}</details></section>')
        return f"<section><h2>{esc(title)} ({len(jobs)})</h2>{cards}</section>"

    def roster_section():
        tiers = {"A": [], "B": [], "C": []}
        for c in companies:
            tiers.setdefault(c["tier"], []).append(c)
        parts = []
        n_on = sum(1 for c in companies if c.get("enabled"))
        for t in ("A", "B", "C"):
            rows = []
            for c in tiers.get(t, []):
                if c.get("enabled"):
                    rows.append(f'<span class="on">{esc(c["name"])}</span>')
                else:
                    rows.append(f'<span class="off" title="{esc(c.get("note") or "pending fingerprint")}">{esc(c["name"])}</span>')
            parts.append(f'<div class="meta" style="margin-top:6px"><b>Tier {t}:</b> '
                         + " &middot; ".join(rows) + "</div>")
        return (f'<section><details class="fold"><summary>Monitored companies '
                f'({n_on} active of {len(companies)})</summary><div class="card">'
                + "".join(parts)
                + '<div class="meta" style="margin-top:10px">Greyed = endpoint pending '
                  'fingerprint (triage queue). Roster grows via discovery &rarr; triage PRs.</div>'
                  '</div></details></section>')

    new_count = sum(1 for j in active if "new" in j["flags"])
    body = f"""<main>
<h1>Unifier job watch</h1>
<div class="sub">Updated {esc(today)} &middot; {len(t1_direct) + len(t2_direct)} direct listings
 &middot; {len(boards)} unresolved board finds &middot; {new_count} new this run</div>
{warn_html}
{section("Unifier — direct listings", t1_direct)}
{section("Related keywords (P6 / OPC / PIF / OIC) — direct listings", t2_direct)}
{section("Unresolved board finds (pending triage)", boards, fold=True)}
{section("No longer listed", gone, fold=True)}
{roster_section()}
<footer>All fields shown verbatim from the source posting — nothing estimated.
Sorted by keyword tier, company tier, stated comp, location.</footer>
</main>"""

    DOCS.mkdir(exist_ok=True)
    page = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<meta name=\"robots\" content=\"noindex\">"
            f"<title>Unifier job watch</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")
    (DOCS / "index.html").write_text(page, encoding="utf-8")
