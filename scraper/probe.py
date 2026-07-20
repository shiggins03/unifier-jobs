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
    """Run one probe; print its traceback instead of killing the run."""
    try:
        fn()
    except Exception:
        print(f"  {label}: EXCEPTION\n{traceback.format_exc()}")


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
    # --- MTA: non-circumvention routes only ---------------------------------
    section("MTA alternate routes")
    for u in ["https://careers.mta.org/robots.txt",
              "https://careers.mta.org/sitemap.xml",
              "https://mta.jibeapply.com/api/jobs?page=1&keyword=unifier",
              "https://careers.mta.org/search/jobs/in/ny-new-york"]:
        show(u, lambda u=u: print(f"  body[:250]={get(u).text[:250]!r}"))

    # --- City of New York: live Unifier posting seen on cityjobs.nyc.gov ----
    section("CITYJOBS NYC")
    for u in ["https://cityjobs.nyc.gov/jobs?q=unifier",
              "https://cityjobs.nyc.gov/api/jobs?q=unifier",
              "https://cityjobs.nyc.gov/job/unifier-coordinator-for-capital-projects-in-queens-jid-27772"]:
        def cj(u=u):
            r = get(u)
            low = r.text.casefold()
            print(f"  unifier-mentions={low.count('unifier')} "
                  f"json={'json' in (r.headers.get('content-type') or '')}")
            print(f"  body[:200]={r.text[:200]!r}")
        show(u, cj)
    def cj_echo():
        a = requests.get("https://cityjobs.nyc.gov/jobs?q=unifier",
                         headers=BROWSER_UA, timeout=T)
        b = requests.get("https://cityjobs.nyc.gov/jobs?q=zzqnope999",
                         headers=BROWSER_UA, timeout=T)
        print(f"  echo test: lenA={len(a.text)} lenB={len(b.text)} "
              f"differs={len(a.text) != len(b.text)}")
    show("echo", cj_echo)

    # --- NYC-area public owners ---------------------------------------------
    section("PORT AUTHORITY NY/NJ")
    for u in ["https://careers.panynj.gov/",
              "https://www.jobapscloud.com/PA/",
              "https://panynj.wd1.myworkdayjobs.com/"]:
        show(u, lambda u=u: get(u))
    section("NYPA")
    for site in ["Careers", "NYPA", "External"]:
        show(site, lambda s=site: cxs("nypa.wd1.myworkdayjobs.com", "nypa", s))
    show("nypa.gov careers", lambda: get("https://www.nypa.gov/careers"))
    section("NYC SCA")
    for u in ["https://www.nycsca.org/Careers",
              "https://careers.nycsca.org/"]:
        show(u, lambda u=u: get(u))
    section("DASNY")
    show("dasny careers", lambda: get("https://www.dasny.org/careers"))
    section("AMTRAK")
    sf_csb("https://careers.amtrak.com", "amtrak SF CSB")
    section("NJ TRANSIT")
    show("njtransit careers", lambda: get("https://careers.njtransit.com/"))

    # --- national E&C / consultancies that recur in Unifier postings --------
    section("WORKDAY GUESSES (E&C)")
    cxs("aecom.wd1.myworkdayjobs.com", "aecom", "AECOM")
    cxs("aecom.wd1.myworkdayjobs.com", "aecom", "External")
    cxs("parsons.wd5.myworkdayjobs.com", "parsons", "ParsonsCareers")
    cxs("parsons.wd5.myworkdayjobs.com", "parsons", "External")
    cxs("stvinc.wd1.myworkdayjobs.com", "stvinc", "STV")
    cxs("stvinc.wd1.myworkdayjobs.com", "stvinc", "External")
    cxs("arcadis.wd3.myworkdayjobs.com", "arcadis", "Arcadis_Careers")
    cxs("arcadis.wd3.myworkdayjobs.com", "arcadis", "External")
    cxs("hillintl.wd1.myworkdayjobs.com", "hillintl", "External")
    cxs("skanska.wd3.myworkdayjobs.com", "skanska", "External")
    section("SF CSB GUESSES (E&C)")
    sf_csb("https://careers.jacobs.com", "jacobs")
    sf_csb("https://careers.hntb.com", "hntb")
    sf_csb("https://jobs.turnerconstruction.com", "turner construction")
    section("MISC CAREERS PAGES")
    for u in ["https://careers.jacobs.com/", "https://careers.hntb.com/",
              "https://www.turnerconstruction.com/careers"]:
        show(u, lambda u=u: get(u))


if __name__ == "__main__":
    main()
