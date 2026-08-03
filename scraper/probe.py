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
    # Round 14: Foresee Consulting (formerly 4C Team, 4cteam.com) — an Oracle
    # Primavera PLATINUM partner whose whole practice is Unifier. Sandbox gets
    # 403 on every path. Questions: (a) what roles do they actually list,
    # (b) is there a scriptable endpoint or is it a mailto-only careers page?
    section("FORESEE / 4C TEAM (4cteam.com)")

    def sniff(url):
        r = get(url)
        if not r.ok:
            return
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        for term in ("unifier", "career", "hiring", "job openings", "resume",
                     "@4cteam.com", "consultant"):
            n = len(re.findall(re.escape(term), text, re.I))
            if n:
                print(f"    '{term}' x{n}")
        # Any ATS the page links out to?
        ats = ("greenhouse", "lever.co", "workday", "myworkdayjobs", "bamboohr",
               "smartrecruiters", "jazzhr", "applytojob", "recruitee", "breezy",
               "workable", "ziprecruiter", "indeed", "paylocity", "adp",
               "successfactors", "icims", "careers")
        links = {a["href"] for a in soup.find_all("a", href=True)}
        for href in sorted(links):
            if any(t in href.lower() for t in ats):
                print(f"    LINK {href[:120]}")
        for m in sorted(set(re.findall(r"[\w.+-]+@[\w.-]+", text)))[:6]:
            print(f"    MAILTO {m}")
        # Headings often carry the job titles on a simple careers page
        for h in soup.find_all(["h1", "h2", "h3", "h4"])[:25]:
            t = h.get_text(" ", strip=True)
            if t:
                print(f"    H: {t[:100]}")

    for path in ("", "/careers/", "/career/", "/careers", "/about/",
                 "/jobs/", "/contact/"):
        show(f"4cteam{path}", lambda p=path: sniff(f"https://4cteam.com{p}"))

    section("4cteam: robots/sitemap (find the real careers URL)")
    def maps():
        for u in ("https://4cteam.com/robots.txt",
                  "https://4cteam.com/sitemap.xml",
                  "https://4cteam.com/sitemap_index.xml",
                  "https://4cteam.com/wp-sitemap.xml"):
            r = requests.get(u, headers=BROWSER_UA, timeout=T)
            print(f"  GET {u} -> {r.status_code} len={len(r.text)}")
            if r.ok:
                for line in r.text.splitlines():
                    if re.search(r"career|job|hiring|position", line, re.I):
                        print(f"    {line.strip()[:150]}")
    show("maps", maps)

    section("Is 4C on a public ATS? (name-based probes)")
    def ats_guess():
        for u in ("https://boards.greenhouse.io/4cteam",
                  "https://boards.greenhouse.io/foreseeconsulting",
                  "https://api.lever.co/v0/postings/4cteam?mode=json",
                  "https://api.lever.co/v0/postings/foresee?mode=json",
                  "https://4cteam.applytojob.com/apply",
                  "https://foreseeconsulting.applytojob.com/apply"):
            try:
                r = requests.get(u, headers=BROWSER_UA, timeout=T,
                                 allow_redirects=True)
                print(f"  {u} -> {r.status_code} len={len(r.text)}")
            except Exception as e:
                print(f"  {u} -> EXC {type(e).__name__}: {str(e)[:80]}")
    show("ats_guess", ats_guess)
    return

    # ---- previous round (Adzuna verification), kept for reference ----
    import os
    section("ADZUNA credential + search verification")
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    print(f"  app_id present: {bool(app_id)} | app_key present: {bool(app_key)}")
    if not (app_id and app_key):
        print("  -> secrets not set yet; add them and re-dispatch")
        return

    def search(what_phrase, label):
        r = requests.get("https://api.adzuna.com/v1/api/jobs/us/search/1",
                         params={"app_id": app_id, "app_key": app_key,
                                 "what_phrase": what_phrase, "max_days_old": 90,
                                 "results_per_page": 50},
                         headers=ADAPTER_UA, timeout=T)
        ct = (r.headers.get("content-type") or "").split(";")[0]
        print(f"  [{label}] HTTP {r.status_code} ctype={ct}")
        quota = {k: v for k, v in r.headers.items()
                 if any(t in k.lower() for t in ("ratelimit", "quota", "limit"))}
        if quota:
            print(f"    quota headers: {quota}")
        if not r.ok:
            body = r.text[:300]
            for secret in (app_id, app_key):
                body = body.replace(secret, "<REDACTED>")
            print(f"    body: {body!r}")
            return []
        d = r.json()
        res = d.get("results", [])
        print(f"    total_available={d.get('count')} returned={len(res)}")
        return res

    for phrase, label in [("Primavera Unifier", 'the pipeline query #1'),
                          ("Oracle Unifier", "the pipeline query #2"),
                          ("zzqnope999", "NEGATIVE CONTROL")]:
        def go(phrase=phrase, label=label):
            res = search(phrase, label)
            for j in res[:10]:
                co = (j.get("company") or {}).get("display_name")
                loc = (j.get("location") or {}).get("display_name")
                sal = ""
                if str(j.get("salary_is_predicted")) == "0" and j.get("salary_min"):
                    sal = f" | ${j.get('salary_min'):,.0f}-${j.get('salary_max') or j.get('salary_min'):,.0f}"
                print(f"      - {co} | {(j.get('title') or '')[:46]} | {loc}{sal}")
            hits = [j for j in res
                    if "mta" in ((j.get("company") or {}).get("display_name") or "").lower()
                    or "metropolitan transportation" in
                       ((j.get("company") or {}).get("display_name") or "").lower()]
            if hits:
                print(f"    *** MTA HITS: {len(hits)} ***")
                for j in hits:
                    print(f"      {j.get('title')} -> {j.get('redirect_url')}")
        show(label, go)

    section("ADZUNA via the real adapter (fetch_adzuna)")
    def adapter():
        records, ok = sources.fetch_adzuna(['"Primavera Unifier"', "Oracle Unifier"])
        print(f"  ok={ok} records={len(records)}")
        for r in records[:12]:
            print(f"    - {r.get('company')} | {(r.get('title') or '')[:44]} | "
                  f"{r.get('location')} | comp={r.get('comp')}")
    show("adapter", adapter)


if __name__ == "__main__":
    main()
