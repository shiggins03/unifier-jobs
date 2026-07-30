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
    section("AMAZON adapter e2e")
    show("amazon", lambda: run_adapter("amazon_jobs", sources.fetch_amazon_jobs,
                                       {"name": "Amazon"}))

    section("NEW WORKDAY configs e2e (does the unifier search yield?)")
    for name, host, tenant, site in [
        ("NVIDIA", "nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite"),
        ("Micron", "micron.wd1.myworkdayjobs.com", "micron", "External"),
        ("Intel", "intel.wd1.myworkdayjobs.com", "intel", "External"),
        ("Pfizer", "pfizer.wd1.myworkdayjobs.com", "pfizer", "PfizerCareers"),
        ("PwC", "pwc.wd3.myworkdayjobs.com", "pwc", "Global_Experienced_Careers"),
    ]:
        show(name, lambda n=name, h=host, t=tenant, s=site: run_adapter(
            f"workday:{n}", sources.fetch_workday,
            {"name": n, "workday_host": h, "workday_tenant": t, "workday_site": s}))

    section("NORTHWELL findly ECHO CONTROL (unifier=15 may be query echo)")
    def findly(q):
        r = get(f"https://northwell.site.findly.com/?s={q}")
        low = r.text.casefold()
        print(f"    q={q!r} len={len(r.text)} echoes={low.count(q.lower())} "
              f"unifier={low.count('unifier')}")
    for q in ("unifier", "zzqnope999"):
        show(q, lambda q=q: findly(q))

    section("ELI LILLY ats hunt (confirmed Unifier user, tenant unknown)")
    def hunt(label, url):
        r = get(url)
        links = sorted(set(re.findall(
            r'https?://[^"\'\s]*(?:myworkdayjobs|myworkdaysite|icims|taleo|'
            r'successfactors|phenom|eightfold|avature|oraclecloud|brassring)'
            r'[^"\'\s]*', r.text)))[:8]
        print(f"    {label}: {links}")
    show("careers.lilly.com", lambda: hunt("lilly", "https://careers.lilly.com/us/en"))
    for site in ["LLY_External", "lillycareers", "LillyCareers", "Lilly_Careers",
                 "EliLilly", "lly"]:
        cxs("lilly.wd5.myworkdayjobs.com", "lilly", site)

    section("MORE ATS HUNTS: J&J / AECOM / Jacobs / KPMG / EY / GM")
    for label, url in [
        ("jnj", "https://www.careers.jnj.com/en"),
        ("aecom", "https://aecom.jobs/"),
        ("jacobs", "https://careers.jacobs.com/en_US/careers"),
        ("kpmg", "https://www.kpmguscareers.com/"),
        ("ey", "https://careers.ey.com/ey/search/"),
        ("gm", "https://search-careers.gm.com/en/jobs/"),
    ]:
        show(label, lambda l=label, u=url: hunt(l, u))


if __name__ == "__main__":
    main()
