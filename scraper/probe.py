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
    # /estimated-salary, /job-details, /company-job-salary => 200.
    # /search and /search-filters => 404 "does not exist".
    # Either the search endpoint was renamed, or the subscribed plan excludes
    # it (RapidAPI reports out-of-plan routes as 404). Settle it.
    import os
    section("JSEARCH: plan headers from a WORKING endpoint")
    key = os.environ.get("JSEARCH_API_KEY")
    if not key:
        print("  no key"); return
    H = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    base = "https://jsearch.p.rapidapi.com"
    def hdrs():
        r = requests.get(base + "/job-details", params={"job_id": "x"},
                         headers=H, timeout=T)
        keep = {k: v for k, v in r.headers.items()
                if any(t in k.lower() for t in
                       ("ratelimit", "quota", "plan", "subscription", "tier",
                        "requests"))}
        print(f"  /job-details {r.status_code}; plan/quota headers:")
        for k, v in sorted(keep.items()):
            print(f"    {k}: {v}")
        if not keep:
            print("    (none exposed)")
    show("headers", hdrs)

    section("JSEARCH: exhaustive search-path sweep")
    paths = ["/jobs", "/job", "/jobs-search", "/find-jobs", "/list-jobs",
             "/search-job", "/searchjobs", "/job/search", "/v1/job-search",
             "/v2/search-jobs", "/search/jobs", "/api/jobs", "/query",
             "/jobs/list", "/jobsearch", "/job-search-v2", "/search_v2",
             "/v3/search"]
    found = []
    for p in paths:
        try:
            r = requests.get(base + p, params={"query": "unifier", "country": "us"},
                             headers=H, timeout=T)
            if r.status_code != 404:
                found.append((p, r.status_code, r.text[:160]))
                print(f"  {p:22s} {r.status_code}  <-- NOT 404")
        except Exception as e:
            print(f"  {p:22s} EXC {type(e).__name__}")
    print(f"  swept {len(paths)} paths; non-404: {len(found)}")

    section("JSEARCH: POST /search (in case the verb changed)")
    def post_search():
        r = requests.post(base + "/search",
                          json={"query": "unifier", "country": "us"},
                          headers=H, timeout=T)
        print(f"  POST /search -> {r.status_code} body={r.text[:160]!r}")
    show("post", post_search)


if __name__ == "__main__":
    main()
