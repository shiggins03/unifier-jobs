"""One-off endpoint diagnostics for broken roster companies (round 2). Runs only
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


def cxs(host, tenant, site):
    u = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    r = requests.post(u, json={"appliedFacets": {}, "limit": 1, "offset": 0,
                               "searchText": ""}, headers=ADAPTER_UA, timeout=T)
    total = None
    if r.ok and "json" in (r.headers.get("content-type") or ""):
        total = r.json().get("total")
    print(f"  POST cxs {host} {tenant}/{site} -> {r.status_code} total={total} "
          f"ctype={r.headers.get('content-type')} body[:150]={r.text[:150]!r}")


def main():
    # --- MGB: web search says tenant renamed to massgeneralbrigham -----------
    section("MGB verify")
    show("MGBExternal", lambda: cxs("massgeneralbrigham.wd1.myworkdayjobs.com",
                                    "massgeneralbrigham", "MGBExternal"))

    # --- Accenture: 200 but non-JSON — see what it actually returns ---------
    section("ACCENTURE cxs raw")
    show("AccentureCareers", lambda: cxs("accenture.wd103.myworkdayjobs.com",
                                         "accenture", "AccentureCareers"))

    # --- WSP: find their real ATS from the corporate careers page -----------
    section("WSP discovery")
    def wsp_page():
        r = get("https://www.wsp.com/en-us/careers/job-opportunities")
        links = sorted(set(re.findall(
            r'https?://[^"\'\s]*(?:myworkdayjobs|successfactors|smartrecruiters|'
            r'taleo|dejobs|icims|greenhouse|lever|phenom|jobs?\.)[^"\'\s]*',
            r.text)))[:20]
        print(f"  ATS-ish links: {links}")
    show("careers page", wsp_page)
    for site in ["WSP_Global", "WSPGlobal", "Careers", "wspcareers",
                 "WSP_External", "WSPUS", "WSP-Global", "Ext", "External_Careers"]:
        show(site, lambda s=site: cxs("wsp.wd3.myworkdayjobs.com", "wsp", s))

    # --- Oracle ORC: works; check whether limit>25 captures all matches -----
    section("ORACLE ORC limits")
    base = ("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions")
    for lim in (50, 100):
        def orc(lim=lim):
            r = requests.get(base, params={
                "onlyData": "true", "expand": "all",
                "finder": f'findReqs;siteNumber=CX_45001,keyword=primavera,limit={lim}'},
                headers=ADAPTER_UA, timeout=T)
            items = r.json().get("items", []) if r.ok else []
            n = len(items[0].get("requisitionList", [])) if items else None
            tot = items[0].get("TotalJobsCount") if items else None
            print(f"  limit={lim} -> {r.status_code} reqs={n} TotalJobsCount={tot}")
        show(f"limit {lim}", orc)

    # --- Turner & Townsend: SmartRecruiters public API ----------------------
    section("T&T SmartRecruiters")
    for slug in ["turnertownsend", "TurnerTownsend", "turner-townsend"]:
        def sr(slug=slug):
            r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
                    f"?q=unifier&limit=10", ua=ADAPTER_UA)
            if r.ok:
                d = r.json()
                print(f"  slug={slug} totalFound={d.get('totalFound')} "
                      f"first={[p.get('name') for p in d.get('content', [])[:3]]}")
        show(slug, sr)
    def sr_inv():
        r = requests.get("https://api.smartrecruiters.com/v1/companies/"
                         "turnertownsend/postings?limit=1", headers=ADAPTER_UA,
                         timeout=T)
        print(f"  inventory (no q) -> {r.status_code} "
              f"totalFound={r.json().get('totalFound') if r.ok else None}")
    show("inventory", sr_inv)

    # --- LA Metro: correct slug is lametro; is the page server-rendered? ----
    section("LA METRO lametro")
    def lametro(q):
        r = get(f"https://www.governmentjobs.com/careers/lametro?keywords={q}")
        low = r.text.casefold()
        print(f"  q={q!r}: mentions-of-q={low.count(q.casefold())} "
              f"job-table-rows={low.count('job-table')} "
              f"list-items={low.count('list-item')}")
        m = re.findall(r'href="(/careers/lametro/jobs/[^"]+)"', r.text)
        print(f"  job links: {len(m)} first3={m[:3]}")
    show("q=primavera", lambda: lametro("primavera"))
    show("q=zzqnope", lambda: lametro("zzqnope"))

    # --- Northwell: WP site — find the real search endpoint -----------------
    section("NORTHWELL search discovery")
    def nw_home():
        r = get("https://jobs.northwell.edu/")
        forms = re.findall(r'<form[^>]+action="([^"]+)"', r.text)
        print(f"  form actions: {forms[:5]}")
        api = sorted(set(re.findall(
            r'https?://[^"\'\s]*(?:search|api|widget)[^"\'\s]*', r.text)))[:15]
        print(f"  search/api-ish urls: {api}")
    show("home", nw_home)
    for u in ["https://jobs.northwell.edu/?s=unifier",
              "https://jobs.northwell.edu/search-jobs/?keyword=unifier",
              "https://jobs.northwell.edu/search/?q=unifier"]:
        show(u, lambda u=u: get(u))

    # --- Burns & McDonnell: burnsmcd.jobs (DirectEmployers) + apply. ATS ----
    section("BURNS MCD boards")
    def bmcd(q):
        r = get(f"https://burnsmcd.jobs/jobs/?q={q}")
        low = r.text.casefold()
        print(f"  q={q!r}: direct-se-hits={low.count('direct_joblisting')} "
              f"'no jobs'={('no jobs' in low) or ('0 jobs' in low)}")
    show("q=primavera", lambda: bmcd("primavera"))
    show("q=zzqnope", lambda: bmcd("zzqnope"))
    def bmcd_apply():
        r = get("https://apply.burnsmcd.com/apply")
        hint = re.findall(r'(avature|icims|workday|successfactors|taleo|'
                          r'smartrecruiters|greenhouse|lever|phenom|jibe|radancy)',
                          r.text, re.I)
        print(f"  ATS fingerprints: {sorted(set(h.lower() for h in hint))}")
    show("apply.burnsmcd.com", bmcd_apply)

    # --- MARTA: where do jobs actually live on itsmarta.com? ----------------
    section("MARTA discovery")
    def marta():
        r = get("https://itsmarta.com/careers.aspx")
        links = sorted(set(re.findall(
            r'https?://[^"\'\s]*(?:icims|jobs|career|taleo|neogov|governmentjobs)'
            r'[^"\'\s]*', r.text)))[:15]
        print(f"  job-ish links: {links}")
    show("careers.aspx", marta)

    # --- Petrofac: www works — false-positive check + find search URL -------
    section("PETROFAC www")
    def petrofac():
        r = get("https://www.petrofac.com/careers")
        low = r.text.casefold()
        print(f"  contains unifier={('unifier' in low)} "
              f"primavera={('primavera' in low)}")
        links = sorted(set(re.findall(
            r'https?://[^"\'\s]*(?:job|vacan|oleeo|successfactors|workday|taleo)'
            r'[^"\'\s]*', r.text)))[:15]
        print(f"  job-ish links: {links}")
    show("careers", petrofac)

    # --- CDP Inc: hunt the careers page via sitemap -------------------------
    section("CDP INC sitemap")
    def cdp():
        r = get("https://www.cdp-inc.com/sitemap.xml")
        if r.ok:
            hits = [u for u in re.findall(r"<loc>([^<]+)</loc>", r.text)
                    if re.search(r"career|job|join|team", u, re.I)]
            print(f"  career-ish sitemap urls: {hits[:10]}")
    show("sitemap", cdp)

    # --- Compass Consult: hunt jobs page via sitemap ------------------------
    section("COMPASS sitemap")
    def compass():
        r = get("https://compassconsult.co/sitemap.xml")
        if r.ok:
            hits = [u for u in re.findall(r"<loc>([^<]+)</loc>", r.text)
                    if re.search(r"career|job|join|team|position", u, re.I)]
            print(f"  career-ish sitemap urls: {hits[:10]}")
        sub = re.findall(r"<loc>([^<]+\.xml)</loc>", r.text)[:10]
        print(f"  sub-sitemaps: {sub}")
    show("sitemap", compass)

    # --- MTA: is anything not behind Cloudflare? ----------------------------
    section("MTA alternates")
    for u in ["https://new.mta.info/careers", "https://www.mta.info/careers"]:
        def mta(u=u):
            r = get(u)
            links = sorted(set(re.findall(
                r'https?://[^"\'\s]*(?:careers|jobs|icims|taleo)[^"\'\s]*',
                r.text)))[:10]
            print(f"  job-ish links: {links}")
        show(u, mta)


if __name__ == "__main__":
    main()
