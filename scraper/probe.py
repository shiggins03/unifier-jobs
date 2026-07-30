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
    # Two key-free leads from round 15. Both need the echo control before
    # being trusted, then the real job rows + employer links extracted.
    section("APTA transit job board (jobs.apta.com)")
    def apta(q):
        r = requests.get("https://jobs.apta.com/jobs/", params={"keywords": q},
                         headers=BROWSER_UA, timeout=T)
        low = r.text.casefold()
        print(f"  q={q!r}: {r.status_code} len={len(r.text)} "
              f"echo={low.count(q.casefold())} unifier={low.count('unifier')} "
              f"mta={low.count('mta')}")
        return r
    show("unifier", lambda: apta("unifier"))
    show("primavera", lambda: apta("primavera"))
    show("control", lambda: apta("zzqnope999"))

    def apta_rows():
        r = apta("unifier")
        soup = BeautifulSoup(r.text, "html.parser")
        # dump candidate row containers so we can pick a stable selector
        for sel in ["a[href*='/job/']", ".bti-job-title a", "h3 a", "article a"]:
            hits = soup.select(sel)
            if hits:
                print(f"  selector {sel!r} -> {len(hits)} matches")
                for a in hits[:6]:
                    print(f"    {a.get_text(' ', strip=True)[:70]!r} -> {a.get('href')}")
                break
        # any structured data?
        ld = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                        r.text, re.S)
        print(f"  JSON-LD blocks: {len(ld)}")
        for blk in ld[:2]:
            print(f"    {blk.strip()[:220]!r}")
    show("apta rows", apta_rows)

    section("GOVERNMENTJOBS cross-agency (governmentjobs.com/jobs?keyword=)")
    def gj(q):
        r = requests.get("https://www.governmentjobs.com/jobs",
                         params={"keyword": q}, headers=BROWSER_UA, timeout=T)
        low = r.text.casefold()
        print(f"  q={q!r}: {r.status_code} len={len(r.text)} "
              f"echo={low.count(q.casefold())} unifier={low.count('unifier')}")
        return r
    show("unifier", lambda: gj("unifier"))
    show("control", lambda: gj("zzqnope999"))

    def gj_rows():
        r = gj("unifier")
        soup = BeautifulSoup(r.text, "html.parser")
        for sel in ["a[href*='/jobs/']", "a[href*='/careers/']", ".job-title a",
                    "h3 a", "[class*=job] a"]:
            hits = soup.select(sel)
            if len(hits) > 3:
                print(f"  selector {sel!r} -> {len(hits)} matches")
                for a in hits[:8]:
                    t = a.get_text(" ", strip=True)[:60]
                    if t:
                        print(f"    {t!r} -> {a.get('href')}")
                break
        ld = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                        r.text, re.S)
        print(f"  JSON-LD blocks: {len(ld)}")
        for blk in ld[:2]:
            print(f"    {blk.strip()[:300]!r}")
    show("gj rows", gj_rows)


if __name__ == "__main__":
    main()
