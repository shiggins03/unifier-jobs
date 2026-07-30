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
    # The owner supplied a working search URL shape we never tested:
    #   /search/jobs?q=unifier&location=
    # Earlier probes used /search/{kw}/jobs and /api/jobs. Different paths can
    # carry different Cloudflare rules, and Actions runs from different IPs
    # than the session proxy — so retest properly before declaring it dead.
    section("MTA /search/jobs query-param shape")
    variants = [
        ("owner URL", "https://careers.mta.org/search/jobs?q=unifier&location="),
        ("no location", "https://careers.mta.org/search/jobs?q=unifier"),
        ("nonsense (control)", "https://careers.mta.org/search/jobs?q=zzqnope999"),
        ("bare search", "https://careers.mta.org/search/jobs"),
        ("json suffix", "https://careers.mta.org/search/jobs.json?q=unifier"),
        ("pages route", "https://careers.mta.org/pages"),
        ("direct job page", "https://careers.mta.org/jobs/"
                            "17757061-advanced-software-engineer-unifier"),
    ]
    for label, u in variants:
        def go(label=label, u=u):
            r = requests.get(u, headers=BROWSER_UA, timeout=T)
            low = r.text.casefold()
            challenge = ("just a moment" in low or "cf-browser-verification" in low
                         or "human verification" in low)
            print(f"  {label}: {r.status_code} len={len(r.text)} "
                  f"challenge={challenge} unifier={low.count('unifier')} "
                  f"server={r.headers.get('server')}")
            if r.ok and not challenge:
                hrefs = sorted(set(re.findall(r'href="(/jobs/\d+[^"]*)"', r.text)))
                print(f"    JOB LINKS ({len(hrefs)}): {hrefs[:8]}")
        show(label, go)

    # If HTML is walled, is there a JSON endpoint behind the same UI?
    section("MTA JSON attempts (Accept: application/json)")
    for u in ["https://careers.mta.org/search/jobs?q=unifier",
              "https://careers.mta.org/api/search/jobs?q=unifier",
              "https://careers.mta.org/api/v1/jobs?q=unifier"]:
        def js(u=u):
            r = requests.get(u, headers={**BROWSER_UA,
                                         "Accept": "application/json"}, timeout=T)
            print(f"  {u} -> {r.status_code} ctype={r.headers.get('content-type')} "
                  f"body[:140]={r.text[:140]!r}")
        show(u, js)

    # Vendor fingerprint: even a block page often names the platform, and
    # knowing the ATS may reveal a reachable vendor-hosted mirror.
    section("MTA vendor fingerprint")
    def fingerprint():
        r = requests.get("https://careers.mta.org/", headers=BROWSER_UA, timeout=T)
        print(f"  / -> {r.status_code} server={r.headers.get('server')} "
              f"powered-by={r.headers.get('x-powered-by')}")
        print(f"  set-cookie: {str(r.headers.get('set-cookie'))[:220]}")
        hits = sorted(set(re.findall(
            r'(jibe|radancy|phenom|icims|workday|smartrecruiters|teamtailor|'
            r'greenhouse|lever|avature|eightfold|talemetry|clinch|symphony)',
            r.text, re.I)))
        print(f"  vendor tokens in body: {hits}")
    show("headers", fingerprint)


if __name__ == "__main__":
    main()
