"""One-off endpoint diagnostics for broken roster companies. Runs only via the
probe workflow (workflow_dispatch) from a network that can reach career sites;
prints findings to the Actions log and writes nothing. Delete probes as their
companies get fixed in companies.yaml."""
import json
import re
import traceback

import requests

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
ADAPTER_UA = {"User-Agent": "unifier-jobs-aggregator (personal job search; contact via repo)"}
T = 25


def section(name):
    print(f"\n{'=' * 20} {name} {'=' * 20}", flush=True)


def show(label, fn):
    try:
        fn()
    except Exception:
        print(f"  {label}: EXCEPTION\n{traceback.format_exc()}")


def get(url, ua=BROWSER_UA, **kw):
    r = requests.get(url, headers=ua, timeout=T, **kw)
    print(f"  GET {url} -> {r.status_code} final={r.url} "
          f"len={len(r.text)} ctype={r.headers.get('content-type')}")
    return r


def workday_probe(label, host, tenant, site_candidates):
    section(f"WORKDAY {label}")

    def landing():
        r = get(f"https://{host}/")
        sites = sorted(set(re.findall(r"/(?:en-US|wday/cxs/[^/]+)/([A-Za-z0-9_\-]+)",
                                      r.text)))
        print(f"  path segments seen in HTML: {sites[:20]}")
        m = re.search(r'"siteId":"([^"]+)"|data-automation-id="siteName"[^>]*>([^<]+)',
                      r.text)
        if m:
            print(f"  site hint: {m.group(0)[:120]}")
    show("landing", landing)

    for site in site_candidates:
        def cxs(site=site):
            u = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
            r = requests.post(u, json={"appliedFacets": {}, "limit": 1, "offset": 0,
                                       "searchText": ""}, headers=ADAPTER_UA, timeout=T)
            total = None
            if r.ok:
                total = r.json().get("total")
            print(f"  POST cxs {tenant}/{site} -> {r.status_code} total={total} "
                  f"body[:120]={r.text[:120]!r}")
        show(f"cxs {site}", cxs)


def main():
    # --- Workday 422s: discover correct tenant/site pairs -------------------
    workday_probe("WSP", "wsp.wd3.myworkdayjobs.com", "wsp",
                  ["WSP", "WSPCareers", "External", "wsp", "Global", "WSP_Careers"])
    workday_probe("Burns & McDonnell", "burnsmcd.wd1.myworkdayjobs.com", "burnsmcd",
                  ["External", "burnsmcd", "BurnsMcD", "careers", "Careers",
                   "External_Careers"])
    workday_probe("Mass General Brigham", "partners.wd1.myworkdayjobs.com", "partners",
                  ["MGB", "PartnersCareers", "External", "MGBcareers", "Careers",
                   "partners"])
    # Accenture: enabled but health shows fail_streak 2 — see which call fails
    workday_probe("Accenture (fail_streak 2)", "accenture.wd103.myworkdayjobs.com",
                  "accenture", ["AccentureCareers"])

    # --- Oracle ORC finder syntax ------------------------------------------
    section("ORACLE ORC")
    base = ("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions")
    for finder in ['findReqs;siteNumber=CX_45001,keyword=primavera,limit=25',
                   'findReqs;siteNumber=CX_45001,keyword="primavera",limit=25',
                   'findReqs;siteNumber=CX_45001,keyword=primavera']:
        def orc(finder=finder):
            r = requests.get(base, params={"onlyData": "true", "expand": "all",
                                           "finder": finder},
                             headers=ADAPTER_UA, timeout=T)
            n = None
            if r.ok:
                items = r.json().get("items", [])
                n = len(items[0].get("requisitionList", [])) if items else 0
            print(f"  finder={finder!r} -> {r.status_code} reqs={n} "
                  f"body[:200]={r.text[:200]!r}")
        show(finder, orc)

    # --- MTA: 403 bot wall — is it UA-based? is there a Jibe JSON API? ------
    section("MTA")
    show("root browser-UA", lambda: get("https://careers.mta.org/"))
    show("search browser-UA", lambda: get("https://careers.mta.org/search/unifier/jobs"))
    show("search adapter-UA",
         lambda: get("https://careers.mta.org/search/unifier/jobs", ua=ADAPTER_UA))
    for u in ["https://careers.mta.org/api/jobs?keywords=unifier&page=1",
              "https://careers.mta.org/api/jobs?q=unifier",
              "https://careers.mta.org/jobs/search?q=unifier"]:
        show(u, lambda u=u: print(f"  body[:300]={get(u).text[:300]!r}"))

    # --- Turner & Townsend: SuccessFactors CSB — find server-side fragment --
    section("TURNER & TOWNSEND")
    for u in ["https://careers.turnerandtownsend.com/tile-search-results/?q=Unifier",
              "https://careers.turnerandtownsend.com/search/?q=Unifier&startrow=0",
              "https://careers.turnerandtownsend.com/go/",
              "https://careers.turnerandtownsend.com/search/?q=zzqnope"]:
        def tt(u=u):
            r = get(u)
            print(f"  contains 'job': {'job' in r.text.casefold()} | "
                  f"tile hits: {r.text.casefold().count('jobtitle')}")
            print(f"  body[:200]={r.text[:200]!r}")
        show(u, tt)

    # --- LA Metro: governmentjobs.com (NeoGov) JSON/RSS candidates ----------
    section("LA METRO (NeoGov)")
    for u in ["https://www.governmentjobs.com/careers/lacmta?keywords=unifier",
              "https://www.governmentjobs.com/careers/lacmta/jobfeed",
              "https://www.governmentjobs.com/careers/home/index?agency=lacmta&keywords=unifier",
              "https://api.governmentjobs.com/v2/postings/lacmta?keyword=unifier"]:
        show(u, lambda u=u: print(f"  body[:300]={get(u).text[:300]!r}"))

    # --- MARTA: verify iCIMS portal ----------------------------------------
    section("MARTA (iCIMS)")
    for u in ["https://careers-martatransit.icims.com/jobs/search?ss=1&searchKeyword=unifier",
              "https://careers-martatransit.icims.com/jobs/search?ss=1&searchKeyword=unifier&in_iframe=1",
              "https://careers-martatransit.icims.com/jobs/intro",
              "https://www.itsmarta.com/careers.aspx"]:
        show(u, lambda u=u: print(f"  body[:200]={get(u).text[:200]!r}"))

    # --- Northwell: Phenom widgets API --------------------------------------
    section("NORTHWELL (Phenom?)")
    def northwell():
        r = requests.post("https://jobs.northwell.edu/widgets", json={
            "lang": "en_us", "deviceType": "desktop", "country": "us",
            "siteType": "external", "pageName": "search-results",
            "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": 0,
            "jobs": True, "counts": True, "all_fields": [], "size": 5,
            "clearAll": False, "jdsource": "facets", "isSliderEnable": False,
            "pageId": "page12", "keywords": "unifier", "global": True},
            headers={**ADAPTER_UA, "Content-Type": "application/json"}, timeout=T)
        hits = None
        if r.ok:
            hits = r.json().get("refineSearch", {}).get("totalHits")
        print(f"  widgets refineSearch -> {r.status_code} totalHits={hits} "
              f"body[:200]={r.text[:200]!r}")
    show("widgets", northwell)
    show("root", lambda: get("https://jobs.northwell.edu/"))

    # --- Petrofac: SSL error ------------------------------------------------
    section("PETROFAC")
    show("careers.petrofac.com", lambda: get("https://careers.petrofac.com/"))
    show("www.petrofac.com/careers",
         lambda: get("https://www.petrofac.com/careers/"))

    # --- CDP Inc: careers 404 — find real URL -------------------------------
    section("CDP INC")
    def cdp():
        r = get("https://www.cdp-inc.com/")
        links = sorted(set(re.findall(r'href="([^"]*(?:career|job)[^"]*)"',
                                      r.text, re.I)))
        print(f"  career-ish links: {links[:10]}")
    show("root", cdp)
    show("old careers URL", lambda: get("https://www.cdp-inc.com/careers"))

    # --- Compass Consult: need jobs-only URL --------------------------------
    section("COMPASS CONSULT")
    def compass():
        r = get("https://compassconsult.co/careers/")
        links = sorted(set(re.findall(
            r'href="([^"]*(?:job|career|position|opening|apply|greenhouse|lever|'
            r'bamboo|workable|recruit)[^"]*)"', r.text, re.I)))
        print(f"  job-ish links: {links[:15]}")
    show("careers page", compass)


if __name__ == "__main__":
    main()
