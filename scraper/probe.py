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
    # --- cityjobs.nyc.gov: echo-safety for the generic_page monitor ---------
    # Config rule: query a DIFFERENT term (primavera) than the checked keyword
    # (unifier). Verify the search is full-text so primavera finds the
    # unifier-titled posting.
    section("CITYJOBS echo safety")
    def cj(q):
        r = get(f"https://cityjobs.nyc.gov/jobs?q={q}")
        low = r.text.casefold()
        print(f"  q={q!r}: len={len(r.text)} unifier-mentions={low.count('unifier')}")
    for q in ("primavera", "zzqnope999"):
        show(q, lambda q=q: cj(q))

    # --- AMTRAK SF CSB: echo baseline + markup sample -----------------------
    section("AMTRAK echo + markup")
    def amtrak(q):
        r = get(f"https://careers.amtrak.com/search/?q={q}")
        low = r.text.casefold()
        print(f"  q={q!r}: len={len(r.text)} unifier={low.count('unifier')} "
              f"title-markers={len(re.findall('jobTitle', r.text))}")
        return r
    show("q=Primavera", lambda: amtrak("Primavera"))
    show("q=zzqnope999", lambda: amtrak("zzqnope999"))
    def amtrak_markup():
        r = amtrak("Unifier")
        rows = re.findall(r'<a[^>]*class="[^"]*jobTitle-link[^"]*"[^>]*>.*?</a>',
                          r.text, re.S)[:4]
        for row in rows:
            print(f"  row: {row[:300]!r}")
        loc = re.findall(r'class="jobLocation"[^>]*>([^<]{1,80})', r.text)[:4]
        print(f"  locations: {loc}")
    show("markup", amtrak_markup)

    # --- Careers pages -> find each org's real ATS link ---------------------
    section("ATS LINK HUNT")
    def links(label, url, pat=r'href="(https?://[^"]*(?:workday|successfactors|icims|taleo|csod|jobaps|governmentjobs|smartrecruiters|greenhouse|lever|phenom|oraclecloud|jibe|avature|inflight|cityjobs)[^"]*)"'):
        r = get(url)
        found = sorted(set(re.findall(pat, r.text, re.I)))[:12]
        print(f"  {label} ATS links: {found}")
    show("panynj", lambda: links("panynj", "https://www.panynj.gov/port-authority/en/careers.html"))
    show("nypa", lambda: links("nypa", "https://www.nypa.gov/careers"))
    show("nycsca", lambda: links("nycsca", "https://www.nycsca.org/Careers/Overview"))
    show("turner", lambda: links("turner", "https://www.turnerconstruction.com/careers"))
    show("dasny", lambda: links("dasny", "https://www.dasny.org/opportunities/employment"))
    show("njtransit", lambda: links("njtransit", "https://www.njtransit.com/careers"))
    show("aecom", lambda: links("aecom", "https://aecom.com/careers/"))
    show("stv", lambda: links("stv", "https://www.stvinc.com/careers"))
    show("arcadis", lambda: links("arcadis", "https://www.arcadis.com/en-us/careers"))
    show("skanska", lambda: links("skanska", "https://www.usa.skanska.com/who-we-are/careers/"))
    show("hill", lambda: links("hill", "https://www.hillintl.com/careers/"))
    show("hntb", lambda: links("hntb", "https://www.hntb.com/careers/"))

    # --- Workday site-name candidates, round 2 ------------------------------
    section("WORKDAY SITES ROUND 2")
    for host, tenant, sites in [
        ("panynj.wd1.myworkdayjobs.com", "panynj",
         ["External", "PANYNJ", "Careers", "PA", "portauthority", "PANYNJ_Careers"]),
        ("nypa.wd1.myworkdayjobs.com", "nypa",
         ["NYPACareers", "nypacareers", "NYPA_Careers", "NYPAExternal", "external"]),
        ("aecom.wd1.myworkdayjobs.com", "aecom",
         ["AECOM_Ext", "AECOMCareers", "aecomcareers", "Ext", "AECOM_Careers", "careers"]),
        ("stvinc.wd1.myworkdayjobs.com", "stvinc",
         ["STVCareers", "stvcareers", "Careers", "STV_External", "STVINC"]),
        ("arcadis.wd3.myworkdayjobs.com", "arcadis",
         ["ArcadisCareers", "Careers", "Ext", "ARCADIS", "Arcadis_External", "GlobalCareers"]),
        ("skanska.wd3.myworkdayjobs.com", "skanska",
         ["SkanskaCareers", "External_Careers", "Careers", "USA", "skanska_ext"]),
        ("hillintl.wd1.myworkdayjobs.com", "hillintl",
         ["HillCareers", "Careers", "hillintl", "Hill_External"]),
    ]:
        for site in sites:
            cxs(host, tenant, site)


if __name__ == "__main__":
    main()
