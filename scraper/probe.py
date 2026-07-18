"""One-off endpoint diagnostics (round 4): end-to-end test of the fixed
adapters (Oracle ORC limit=100, SmartRecruiters T&T, Workday MGB) plus final
discovery for MARTA / WSP-via-dejobs / LA Metro RSS / BurnsMcD ATS / Compass.
Runs only via the probe workflow (workflow_dispatch); writes nothing."""
import re
import traceback

import requests

from . import sources

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
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


def run_adapter(name, fn, co):
    records, ok, inventory = fn(co, "unifier")
    print(f"  {name}: ok={ok} inventory={inventory} records={len(records)}")
    for r in records[:8]:
        print(f"    - {r.get('title')!r} @ {r.get('location')!r} "
              f"desc-len={len(r.get('description') or '') or None} "
              f"search_matched={r.get('search_matched')}")
    return records


def main():
    # --- fixed adapters, called exactly as the pipeline would ---------------
    section("ADAPTER E2E: Oracle ORC (limit=100)")
    show("oracle", lambda: run_adapter("oracle_orc", sources.fetch_oracle_orc, {
        "name": "Oracle",
        "url": "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
               "recruitingCEJobRequisitions",
        "site_number": "CX_45001", "search_query": "primavera"}))

    section("ADAPTER E2E: SmartRecruiters Turner & Townsend")
    show("smartrecruiters", lambda: run_adapter(
        "smartrecruiters", sources.fetch_smartrecruiters,
        {"name": "Turner & Townsend", "smartrecruiters_company": "turnertownsend"}))

    section("ADAPTER E2E: Workday MGB")
    show("workday", lambda: run_adapter("workday", sources.fetch_workday, {
        "name": "Mass General Brigham",
        "workday_host": "massgeneralbrigham.wd1.myworkdayjobs.com",
        "workday_tenant": "massgeneralbrigham", "workday_site": "MGBExternal"}))

    # --- MARTA: is current-job-openings.aspx server-rendered? ---------------
    section("MARTA current-job-openings")
    def marta():
        r = get("https://itsmarta.com/current-job-openings.aspx")
        low = r.text.casefold()
        titles = len(re.findall(r'icims|jobtitle|job-title|posting', low))
        print(f"  job-markers={titles} unifier={'unifier' in low} "
              f"iframe={'<iframe' in low}")
        ifr = re.findall(r'<iframe[^>]+src="([^"]+)"', r.text)
        print(f"  iframes: {ifr[:5]}")
        links = sorted(set(re.findall(r'href="(https?://[^"]+)"', r.text)))
        job_links = [u for u in links if re.search(r"icims|job|career", u, re.I)]
        print(f"  external job links: {job_links[:10]}")
    show("page", marta)

    # --- WSP: DirectEmployers mirror (wspgroup.dejobs.org) ------------------
    section("WSP dejobs mirror")
    def wsp_dejobs(q):
        r = get(f"https://wspgroup.dejobs.org/jobs/?q={q}")
        low = r.text.casefold()
        n = len(re.findall(r'direct_joblisting', low))
        print(f"  q={q!r}: direct_joblisting-count={n} "
              f"unifier-mentions={low.count('unifier')}")
    show("q=unifier", lambda: wsp_dejobs("unifier"))
    show("q=primavera", lambda: wsp_dejobs("primavera"))
    show("q=zzqnope", lambda: wsp_dejobs("zzqnope"))

    # --- LA Metro: legacy NeoGov RSS ----------------------------------------
    section("LA METRO legacy RSS")
    for u in ["https://agency.governmentjobs.com/lametro/default.cfm?action=rss",
              "https://agency.governmentjobs.com/lametro/default.cfm?action=jobfeed"]:
        show(u, lambda u=u: print(f"  body[:300]={get(u).text[:300]!r}"))

    # --- Burns McD: identify the ATS behind apply.burnsmcd.com --------------
    section("BURNS MCD apply site scripts")
    def bmcd():
        r = get("https://apply.burnsmcd.com/apply")
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
        print(f"  scripts: {scripts[:10]}")
        links = re.findall(r'href="([^"]+)"', r.text)
        print(f"  links: {links[:10]}")
        print(f"  body[:400]={r.text[:400]!r}")
    show("apply", bmcd)

    # --- Compass: grep all sitemap pages for career/job ---------------------
    section("COMPASS full page grep")
    def compass():
        r = requests.get("https://compassconsult.co/page-sitemap.xml",
                         headers=BROWSER_UA, timeout=T)
        urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
        hits = [u for u in urls if re.search(r"career|job|join|vacan|hiring|team",
                                             u, re.I)]
        print(f"  {len(urls)} pages; career-ish: {hits}")
    show("grep", compass)


if __name__ == "__main__":
    main()
