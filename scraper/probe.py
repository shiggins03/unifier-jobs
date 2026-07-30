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
from bs4 import BeautifulSoup

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
    # 404 "Endpoint '/search' does not exist" => auth is fine, the path is
    # stale. Find the current one empirically instead of guessing in prod.
    import os
    section("JSEARCH endpoint discovery")
    key = os.environ.get("JSEARCH_API_KEY")
    if not key:
        print("  no key visible"); return
    H = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    base = "https://jsearch.p.rapidapi.com"

    def hit(path, params=None):
        try:
            r = requests.get(base + path, params=params or {}, headers=H, timeout=T)
        except Exception as e:
            print(f"  {path:26s} EXC {type(e).__name__}"); return
        body = r.text[:200]
        if key in body:
            body = body.replace(key, "<REDACTED>")
        marker = ""
        if r.ok:
            try:
                d = r.json()
                n = len(d.get("data") or []) if isinstance(d, dict) else 0
                marker = f"  <-- OK status={d.get('status')} data={n}"
            except Exception:
                marker = "  <-- OK (non-json)"
        print(f"  {path:26s} {r.status_code}{marker}")
        if not r.ok:
            print(f"      {body!r}")

    # root + documented-ish siblings first: whichever answers tells us the
    # API is alive and which family of paths is current
    for p in ["/", "/search", "/v1/search", "/v2/search", "/search-jobs",
              "/job-search", "/jobs/search", "/api/search", "/api/v1/search"]:
        hit(p, {"query": "unifier", "country": "us"})

    section("JSEARCH sibling endpoints (confirm which exist)")
    hit("/search-filters", {"query": "unifier", "country": "us"})
    hit("/estimated-salary", {"job_title": "engineer", "location": "new york",
                              "location_type": "ANY"})
    hit("/job-details", {"job_id": "test"})
    hit("/company-job-salary", {"company": "amazon", "job_title": "engineer"})


if __name__ == "__main__":
    main()
