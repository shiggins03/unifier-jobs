"""One-off endpoint diagnostics for broken roster companies (round 3). Runs only
via the probe workflow (workflow_dispatch) from a network that can reach career
sites; prints findings to the Actions log and writes nothing. Delete probes as
their companies get fixed in companies.yaml."""
import json
import re
import traceback

import requests

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
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


def main():
    # --- ORACLE ORC: why do all 27 search hits die in the pipeline? ---------
    # Theory: the detail fetch (description) silently fails, so keyword_tier
    # sees title-only and drops everything. Exercise the detail endpoint
    # exactly as fetch_oracle_orc does, then with variants.
    section("ORACLE ORC details")
    base = ("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions")
    dbase = base.replace("recruitingCEJobRequisitions",
                         "recruitingCEJobRequisitionDetails")
    r = requests.get(base, params={
        "onlyData": "true", "expand": "all",
        "finder": 'findReqs;siteNumber=CX_45001,keyword=primavera,limit=50'},
        headers=ADAPTER_UA, timeout=T)
    reqs = r.json()["items"][0]["requisitionList"]
    print(f"  search -> {r.status_code} reqs={len(reqs)}")
    print(f"  first req keys: {sorted(reqs[0].keys())}")
    rid = reqs[0].get("Id")
    title = reqs[0].get("Title")
    print(f"  probing details for Id={rid!r} Title={title!r}")
    variants = [
        ("adapter-as-is", {"onlyData": "true",
                           "finder": f'ById;Id="{rid}",siteNumber=CX_45001'}),
        ("with expand=all", {"onlyData": "true", "expand": "all",
                             "finder": f'ById;Id="{rid}",siteNumber=CX_45001'}),
        ("unquoted Id", {"onlyData": "true", "expand": "all",
                         "finder": f'ById;Id={rid},siteNumber=CX_45001'}),
    ]
    for name, params in variants:
        def det(name=name, params=params):
            d = requests.get(dbase, params=params, headers=ADAPTER_UA, timeout=T)
            desc = None
            items = []
            if d.ok and "json" in (d.headers.get("content-type") or ""):
                items = d.json().get("items", [])
                if items:
                    desc = items[0].get("ExternalDescriptionStr")
                    print(f"  {name} -> {d.status_code} items={len(items)} "
                          f"item keys sample: {sorted(items[0].keys())[:15]}")
            print(f"  {name} -> {d.status_code} desc-len="
                  f"{len(desc) if desc else None} "
                  f"body[:150]={d.text[:150]!r}" if not desc else
                  f"  {name}: DESC OK len={len(desc)} "
                  f"unifier={'unifier' in desc.casefold()} "
                  f"p6={'p6' in desc.casefold()}")
        show(name, det)

    # If a variant works, sweep all 27 and count which would pass the tier
    # filter (unifier as tier1; P6/OPC/PIF/OIC with primavera/oracle context).
    def sweep():
        pass_count, examples = 0, []
        for q in reqs:
            rid = q.get("Id")
            d = requests.get(dbase, params={
                "onlyData": "true", "expand": "all",
                "finder": f'ById;Id="{rid}",siteNumber=CX_45001'},
                headers=ADAPTER_UA, timeout=T)
            desc = ""
            if d.ok and "json" in (d.headers.get("content-type") or ""):
                items = d.json().get("items", [])
                if items:
                    desc = items[0].get("ExternalDescriptionStr") or ""
            text = f"{q.get('Title', '')}\n{desc}"
            low = text.casefold()
            t1 = bool(re.search(r"\bunifier\b", low))
            ctx = any(c in low for c in ("primavera", "oracle", "project controls"))
            t2 = ctx and bool(re.search(r"\b(P6|OPC|PIF|OIC)\b", text))
            if t1 or t2:
                pass_count += 1
                if len(examples) < 5:
                    examples.append((q.get("Title"), "t1" if t1 else "t2"))
        print(f"  {pass_count}/{len(reqs)} reqs would pass the tier filter")
        for e in examples:
            print(f"    e.g. {e}")
    show("sweep all reqs", sweep)

    # --- ACCENTURE: does the cxs API answer a browser-ish request? ----------
    section("ACCENTURE cxs UA test")
    for ua_name, ua in [("adapter UA + Accept json",
                         {**ADAPTER_UA, "Accept": "application/json"}),
                        ("browser UA + Accept json",
                         {"User-Agent": BROWSER_UA["User-Agent"],
                          "Accept": "application/json"})]:
        def acc(ua_name=ua_name, ua=ua):
            r = requests.post("https://accenture.wd103.myworkdayjobs.com/wday/cxs/"
                              "accenture/AccentureCareers/jobs",
                              json={"appliedFacets": {}, "limit": 1, "offset": 0,
                                    "searchText": ""}, headers=ua, timeout=T)
            ctype = r.headers.get("content-type")
            total = (r.json().get("total")
                     if r.ok and "json" in (ctype or "") else None)
            print(f"  {ua_name} -> {r.status_code} ctype={ctype} total={total}")
        show(ua_name, acc)

    # --- LA METRO: find the SPA's real data endpoint ------------------------
    section("LA METRO api discovery")
    def lametro_page():
        r = get("https://www.governmentjobs.com/careers/lametro")
        hints = sorted(set(re.findall(
            r'["\'](/careers/[^"\']*(?:api|search|jobs)[^"\']*)["\']', r.text)))[:15]
        print(f"  inline api-ish paths: {hints}")
        scripts = sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', r.text)))[:10]
        print(f"  scripts: {scripts}")
    show("page", lametro_page)
    for u in ["https://www.governmentjobs.com/careers/lametro/jobs.rss",
              "https://www.governmentjobs.com/jobfeed/lametro",
              "https://www.governmentjobs.com/careers/lametro/jobs?keywords=unifier"]:
        show(u, lambda u=u: print(f"  body[:200]={get(u).text[:200]!r}"))

    # --- NORTHWELL: the search form posts to /job-search-results/ -----------
    section("NORTHWELL job-search-results")
    def nw_form():
        r = get("https://jobs.northwell.edu/")
        m = re.search(r'<form[^>]+action="/job-search-results/"(.*?)</form>',
                      r.text, re.S)
        if m:
            inputs = re.findall(r'<(?:input|select)[^>]+name="([^"]+)"', m.group(1))
            print(f"  form input names: {inputs}")
    show("form inputs", nw_form)
    for u in ["https://jobs.northwell.edu/job-search-results/?keyword=unifier",
              "https://jobs.northwell.edu/job-search-results/?search=unifier",
              "https://jobs.northwell.edu/job-search-results/?kw=zzqnope"]:
        def nws(u=u):
            r = get(u)
            low = r.text.casefold()
            print(f"  results-markers: 'no results'={('no result' in low)} "
                  f"job-count-hits={len(re.findall(r'job[_-]?(?:result|listing|card)', low))}")
        show(u, nws)

    # --- BURNS MCD: DirectEmployers ajax search -----------------------------
    section("BURNS MCD ajax")
    for u in ["https://burnsmcd.jobs/ajax/jobs/search-and-render/?q=primavera&num_items=10",
              "https://burnsmcd.jobs/ajax/jobs/search/?q=primavera"]:
        def bma(u=u):
            r = get(u)
            print(f"  body[:250]={r.text[:250]!r}")
        show(u, bma)
    def bmcd_page_hints():
        r = get("https://burnsmcd.jobs/jobs/?q=primavera")
        hints = sorted(set(re.findall(r'["\'](/[^"\']*ajax[^"\']*)["\']', r.text)))[:10]
        print(f"  ajax-ish paths in page: {hints}")
    show("page hints", bmcd_page_hints)

    # --- MARTA: relative links + iframes on careers.aspx --------------------
    section("MARTA relative links")
    def marta():
        r = get("https://itsmarta.com/careers.aspx")
        links = sorted(set(re.findall(
            r'(?:href|src)="([^"]*(?:job|career|icims|apply)[^"]*)"', r.text,
            re.I)))[:20]
        print(f"  job-ish hrefs/srcs: {links}")
    show("careers.aspx", marta)

    # --- PETROFAC: relative job links on www careers page -------------------
    section("PETROFAC relative links")
    def petrofac():
        r = get("https://www.petrofac.com/careers")
        links = sorted(set(re.findall(
            r'href="([^"]*(?:job|vacan|opportunit|search)[^"]*)"', r.text,
            re.I)))[:20]
        print(f"  job-ish hrefs: {links}")
    show("careers", petrofac)

    # --- CDP INC: guess paths + homepage nav --------------------------------
    section("CDP INC paths")
    for u in ["https://www.cdp-inc.com/content/careers",
              "https://www.cdp-inc.com/about",
              "https://www.cdp-inc.com/about-us"]:
        show(u, lambda u=u: get(u))
    def cdp_nav():
        r = get("https://www.cdp-inc.com/")
        links = sorted(set(re.findall(r'href="(/[^"]*)"', r.text)))
        print(f"  all internal paths ({len(links)}): {links[:40]}")
    show("nav", cdp_nav)

    # --- COMPASS: page sitemap ----------------------------------------------
    section("COMPASS pages")
    def compass():
        r = get("https://compassconsult.co/page-sitemap.xml")
        urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
        print(f"  pages ({len(urls)}): {urls[:30]}")
    show("page-sitemap", compass)


if __name__ == "__main__":
    main()
