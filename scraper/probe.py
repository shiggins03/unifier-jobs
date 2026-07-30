"""Reusable endpoint-diagnostics harness. The repo's local sandbox (Claude
sessions) usually can't reach career sites, but GitHub Actions can: write
probes into main(), push, dispatch the `probe` workflow (workflow_dispatch
only), read the Actions log, iterate. Keep main() empty between
investigations; findings belong in companies.yaml notes / CLAUDE.md.

History: rounds 1-4 on 2026-07-18 diagnosed the whole broken-roster backlog —
see the notes in companies.yaml and the probe-workflow section in CLAUDE.md."""
import re
import traceback

import requests

from . import sources  # adapters can be exercised end-to-end, see run_adapter

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
ADAPTER_UA = sources.UA
T = 25


def section(name):
    print(f"\n{'=' * 20} {name} {'=' * 20}", flush=True)


def show(label, fn):
    """Run one probe; print a one-line error instead of killing the run.
    (Full tracebacks drown the Actions log — round 5 lesson.)"""
    try:
        fn()
    except Exception as e:
        print(f"  {label}: EXC {type(e).__name__}: {str(e)[:160]}")


def get(url, ua=BROWSER_UA, **kw):
    r = requests.get(url, headers=ua, timeout=T, **kw)
    print(f"  GET {url} -> {r.status_code} final={r.url} "
          f"len={len(r.text)} ctype={r.headers.get('content-type')}")
    return r


def run_adapter(name, fn, co, query="unifier"):
    """Call a direct adapter exactly as the pipeline would and dump results."""
    records, ok, inventory = fn(co, query)
    print(f"  {name}: ok={ok} inventory={inventory} records={len(records)}")
    for r in records[:8]:
        print(f"    - {r.get('title')!r} @ {r.get('location')!r} "
              f"desc-len={len(r.get('description') or '') or None} "
              f"search_matched={r.get('search_matched')}")
    return records


def cxs(host, tenant, site):
    """Quick Workday public-API check: 200+total = right pair, 422 = wrong."""
    try:
        r = requests.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                          json={"appliedFacets": {}, "limit": 1, "offset": 0,
                                "searchText": ""}, headers=ADAPTER_UA, timeout=T)
        total = None
        if r.ok and "json" in (r.headers.get("content-type") or ""):
            total = r.json().get("total")
        print(f"  cxs {host} {tenant}/{site} -> {r.status_code} total={total}")
    except Exception as e:
        print(f"  cxs {host} {tenant}/{site} -> EXC {type(e).__name__}: {e}")


def sf_csb(base, label):
    """SuccessFactors Career Site Builder echo test: server-rendered search
    is usable as generic_page; identical HTML for real vs nonsense query
    means JS-rendered (blind)."""
    try:
        a = requests.get(f"{base}/search/?q=Unifier", headers=BROWSER_UA,
                         timeout=T)
        b = requests.get(f"{base}/search/?q=zzqnope999", headers=BROWSER_UA,
                         timeout=T)
        differs = len(a.text) != len(b.text)
        hits = len(re.findall(r'class="jobTitle|data-careersite-propertyid="title',
                              a.text))
        print(f"  {label}: {a.status_code} lenA={len(a.text)} lenB={len(b.text)} "
              f"differs={differs} title-markers={hits}")
    except Exception as e:
        print(f"  {label}: EXC {type(e).__name__}: {e}")


def main():
    # GOAL: a fully automated route to MTA (and other Cloudflare-walled
    # employers) that needs NO API key and NO human step. MTA syndicates
    # postings, so look for a reachable aggregator that carries them. Per
    # hard rule #4 an aggregator is discovery-only: we resolve each hit back
    # to the employer's own posting URL.
    def show_json(label, url, headers=None, pick=None):
        r = requests.get(url, headers={**BROWSER_UA, **(headers or {})}, timeout=T)
        ct = r.headers.get("content-type") or ""
        print(f"  {label}: {r.status_code} ctype={ct.split(';')[0]} len={len(r.text)}")
        if r.ok and "json" in ct:
            try:
                d = r.json()
            except Exception:
                print(f"    unparseable json: {r.text[:120]!r}"); return
            print(f"    top-level: {list(d)[:8] if isinstance(d, dict) else type(d).__name__}")
            if pick:
                try:
                    print(f"    {pick(d)}")
                except Exception as e:
                    print(f"    pick failed: {e}")
        else:
            low = r.text.casefold()
            print(f"    challenge={'just a moment' in low} "
                  f"mta={low.count('mta')} unifier={low.count('unifier')}")

    section("THE MUSE public API (no key required)")
    show_json("muse unifier",
              "https://www.themuse.com/api/public/jobs?page=0&q=unifier",
              pick=lambda d: f"count={len(d.get('results', []))} "
                             f"first={[j.get('name') for j in d.get('results', [])[:3]]}")

    section("CAREERJET public search (no key)")
    for u in ["https://www.careerjet.com/search/jobs?s=unifier&l=New+York",
              "http://public.api.careerjet.net/search?keywords=unifier&location=new+york"
              "&affid=213e213hd12344&user_ip=1.2.3.4&user_agent=probe&url=http://x"]:
        show_json(u[:52], u)

    section("GOVERNMENTJOBS cross-agency search (reachable earlier)")
    for u in ["https://www.governmentjobs.com/careers?keyword=unifier",
              "https://www.governmentjobs.com/jobs?keyword=unifier"]:
        def gj(u=u):
            r = requests.get(u, headers=BROWSER_UA, timeout=T)
            low = r.text.casefold()
            print(f"  {u[-38:]}: {r.status_code} len={len(r.text)} "
                  f"unifier={low.count('unifier')} mta={low.count('mta')}")
        show(u, gj)

    section("CAREERS IN GOVERNMENT / transit boards")
    for label, u in [
        ("careersingovernment", "https://www.careersingovernment.com/jobs/?keyword=unifier"),
        ("transitjobs", "https://www.transitjobs.com/search?q=unifier"),
        ("apta careers", "https://jobs.apta.com/jobs/?keywords=unifier"),
        ("statejobsny", "https://statejobs.ny.gov/public/vacancySearch.cfm?keyword=unifier"),
    ]:
        def gen(label=label, u=u):
            r = requests.get(u, headers=BROWSER_UA, timeout=T, allow_redirects=True)
            low = r.text.casefold()
            print(f"  {label}: {r.status_code} final={r.url[:60]} len={len(r.text)} "
                  f"challenge={'just a moment' in low} unifier={low.count('unifier')} "
                  f"mta={low.count('mta')}")
        show(label, gen)

    section("ADZUNA / JSEARCH / JOOBLE key status (already coded in sources.py)")
    import os
    for k in ("JSEARCH_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY"):
        print(f"  {k}: {'SET' if os.environ.get(k) else 'not set'}")


if __name__ == "__main__":
    main()
