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
    # The daily run recorded jsearch fail_streak=1 with zero results, and
    # fetch_jsearch swallows the exception — so surface the real status and
    # body here. NEVER print the key itself.
    import os
    section("JSEARCH diagnosis")
    key = os.environ.get("JSEARCH_API_KEY")
    print(f"  key present: {bool(key)} len={len(key) if key else 0}")
    if not key:
        print("  -> secret not visible to this workflow")
        return
    for label, params in [
        ('quoted phrase (what the pipeline sends)',
         {"query": '"Primavera Unifier"', "country": "us", "num_pages": 1}),
        ('plain', {"query": "Oracle Unifier", "country": "us", "num_pages": 1}),
        ('minimal', {"query": "unifier"}),
    ]:
        def call(label=label, params=params):
            r = requests.get("https://jsearch.p.rapidapi.com/search",
                             params=params,
                             headers={"X-RapidAPI-Key": key,
                                      "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
                             timeout=T)
            body = r.text[:400]
            if key in body:
                body = body.replace(key, "<REDACTED>")
            print(f"  {label}: HTTP {r.status_code}")
            rl = {k: v for k, v in r.headers.items()
                  if "ratelimit" in k.lower() or "quota" in k.lower()}
            if rl:
                print(f"    quota: {rl}")
            if r.ok:
                try:
                    d = r.json()
                    jobs = d.get("data") or []
                    print(f"    status={d.get('status')} results={len(jobs)}")
                    for j in jobs[:10]:
                        direct = [o.get("apply_link") for o in (j.get("apply_options") or [])
                                  if o.get("is_direct")]
                        print(f"      - {j.get('employer_name')} | "
                              f"{(j.get('job_title') or '')[:46]} | "
                              f"{j.get('job_city')},{j.get('job_state')} | "
                              f"direct={bool(direct)}")
                        if direct:
                            print(f"          {direct[0][:100]}")
                except Exception as e:
                    print(f"    json parse failed: {e}")
            else:
                print(f"    body: {body!r}")
        show(label, call)


if __name__ == "__main__":
    main()
