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
    # ================= NEW CANDIDATES: public job APIs =================
    section("AMAZON amazon.jobs public JSON")
    def amazon(q):
        r = requests.get("https://www.amazon.jobs/en/search.json",
                         params={"base_query": q, "result_limit": 10},
                         headers=BROWSER_UA, timeout=T)
        if r.ok and "json" in (r.headers.get("content-type") or ""):
            d = r.json()
            hits = d.get("jobs", [])
            print(f"  q={q!r} -> {r.status_code} hits={d.get('hits')} "
                  f"first={[j.get('title') for j in hits[:3]]}")
        else:
            print(f"  q={q!r} -> {r.status_code} ctype={r.headers.get('content-type')} "
                  f"body[:120]={r.text[:120]!r}")
    for q in ("unifier", "primavera", "zzqnope999"):
        show(q, lambda q=q: amazon(q))

    section("MICROSOFT gcs careers API")
    def msft(q):
        r = requests.get("https://gcsservices.careers.microsoft.com/search/api/v1/search",
                         params={"q": q, "l": "en_us", "pg": 1, "pgSz": 20,
                                 "o": "Relevance", "flt": "true"},
                         headers=BROWSER_UA, timeout=T)
        if r.ok and "json" in (r.headers.get("content-type") or ""):
            res = (r.json().get("operationResult") or {}).get("result") or {}
            jobs = res.get("jobs", [])
            print(f"  q={q!r} -> total={res.get('totalJobs')} "
                  f"first={[j.get('title') for j in jobs[:3]]}")
        else:
            print(f"  q={q!r} -> {r.status_code} ctype={r.headers.get('content-type')}")
    for q in ("unifier", "primavera", "zzqnope999"):
        show(q, lambda q=q: msft(q))

    section("APPLE jobs API")
    def apple(q):
        r = requests.post("https://jobs.apple.com/api/role/search",
                          json={"query": q, "filters": {}, "page": 1,
                                "locale": "en-us", "sort": "relevance"},
                          headers={**BROWSER_UA, "Content-Type": "application/json"},
                          timeout=T)
        print(f"  q={q!r} -> {r.status_code} ctype={r.headers.get('content-type')} "
              f"body[:180]={r.text[:180]!r}")
    for q in ("unifier", "zzqnope999"):
        show(q, lambda q=q: apple(q))

    section("GOOGLE careers API (currently-blind generic_page)")
    for u in ["https://careers.google.com/api/v3/search/?q=unifier",
              "https://www.google.com/about/careers/applications/api/v3/search/?q=unifier",
              "https://careers.google.com/api/v2/jobs/search/?q=unifier"]:
        show(u, lambda u=u: print(f"    body[:200]={get(u).text[:200]!r}"))

    # ================= NEW CANDIDATES: Workday tenants =================
    section("WORKDAY: new tier-A/B candidates")
    for host, tenant, sites in [
        # pharma / life sciences (huge capital programs, Lilly confirmed Unifier)
        ("lilly.wd5.myworkdayjobs.com", "lilly", ["LLY", "lilly", "External"]),
        ("pfizer.wd1.myworkdayjobs.com", "pfizer", ["PfizerCareers", "External"]),
        ("jnj.wd5.myworkdayjobs.com", "jnj", ["jnjcareers", "External"]),
        # semis / tech infra
        ("nvidia.wd5.myworkdayjobs.com", "nvidia",
         ["NVIDIAExternalCareerSite", "External"]),
        ("intel.wd1.myworkdayjobs.com", "intel", ["External", "IntelCareers"]),
        ("micron.wd1.myworkdayjobs.com", "micron", ["External", "MicronCareers"]),
        ("gm.wd5.myworkdayjobs.com", "gm", ["External", "GM"]),
        # elite consulting (Unifier implementers)
        ("kpmg.wd12.myworkdayjobs.com", "kpmg", ["External", "KPMGCareers"]),
        ("ey.wd3.myworkdayjobs.com", "ey", ["EY_Careers", "External"]),
        ("pwc.wd3.myworkdayjobs.com", "pwc",
         ["Global_Experienced_Careers", "External"]),
        # E&C still unresolved
        ("aecom.wd1.myworkdayjobs.com", "aecom", ["AECOM_External", "aecom"]),
        ("jacobs.wd1.myworkdayjobs.com", "jacobs", ["External", "Jacobs"]),
    ]:
        for site in sites:
            cxs(host, tenant, site)

    # ================= FIX ATTEMPTS: broken roster =================
    section("NORTHWELL findly (site search hinted northwell.site.findly.com)")
    for u in ["https://northwell.site.findly.com/?s=unifier",
              "https://jobs.northwell.edu/job-search-results/?keyword=primavera"]:
        def nw(u=u):
            r = get(u)
            low = r.text.casefold()
            print(f"    unifier={low.count('unifier')} primavera={low.count('primavera')}")
        show(u, nw)

    section("TURNER CONSTRUCTION csod public API")
    for u in ["https://turnerconstruction.csod.com/services/x/career-site/v1/search"
              "?careerSiteId=1&pageSize=25&keyword=unifier",
              "https://turnerconstruction.csod.com/services/x/career-site/v2/search"
              "?career_site_id=1&keyword=unifier"]:
        show(u, lambda u=u: print(f"    body[:220]={get(u).text[:220]!r}"))

    section("LA METRO / MARTA / PANYNJ / NYPA alt boards")
    for label, u in [
        ("lametro NEOGOV api", "https://www.governmentjobs.com/careers/lametro/jobs.json?keyword=unifier"),
        ("marta icims rss", "https://careers-martatransit.icims.com/jobs/search?ss=1&searchKeyword=unifier&mobile=false&format=rss"),
        ("panynj jobapscloud", "https://www.jobapscloud.com/panynj/"),
        ("panynj careers", "https://www.panynj.gov/corporate/en/careers.html"),
        ("nypa careers alt", "https://www.nypa.gov/careers/career-opportunities"),
    ]:
        show(label, lambda u=u, label=label: print(f"    {label}: body[:180]={get(u).text[:180]!r}"))

    section("WSP / BURNS MCD: find a real job link (gives the Workday site name)")
    for label, u in [
        ("wsp jobs subdomain", "https://jobs.wsp.com/"),
        ("wsp careers alt", "https://www.wsp.com/en-US/careers"),
        ("burnsmcd careers", "https://www.burnsmcd.com/careers"),
    ]:
        def hunt(u=u, label=label):
            r = get(u)
            links = sorted(set(re.findall(
                r'https?://[^"\'\s]*(?:myworkdayjobs|myworkdaysite|icims|taleo|'
                r'successfactors|phenom|eightfold|avature)[^"\'\s]*', r.text)))[:8]
            print(f"    {label} ATS links: {links}")
        show(label, hunt)


if __name__ == "__main__":
    main()
