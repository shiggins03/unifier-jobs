"""Source adapters. Direct ATS adapters return structured listings; generic_page
returns triage entries (the script never parses arbitrary page structure).
Discovery adapters skip silently when their API key isn't configured.
Direct adapters return (records, ok, inventory): inventory is the source's TOTAL
visible job count regardless of keyword (aliveness check — 0 or None-when-expected
means the monitor may be blind, not that no jobs match). Discovery adapters
return (records, ok)."""
import html
import json
import os
import re

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "unifier-jobs-aggregator (personal job search; contact via repo)"}
TIMEOUT = 30


def _clean_html(fragment):
    if not fragment:
        return None
    text = BeautifulSoup(html.unescape(fragment), "html.parser").get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def fetch_workday(co, query):
    host, tenant, site = co["workday_host"], co["workday_tenant"], co["workday_site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    try:
        r = requests.post(url, json={"appliedFacets": {}, "limit": 20, "offset": 0,
                                     "searchText": query}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        postings = r.json().get("jobPostings", [])
    except Exception:
        return [], False, None
    inventory = None
    try:
        inv = requests.post(url, json={"appliedFacets": {}, "limit": 1, "offset": 0,
                                       "searchText": ""}, headers=UA, timeout=TIMEOUT)
        if inv.ok:
            inventory = inv.json().get("total")
    except Exception:
        pass
    out = []
    for p in postings:
        path = p.get("externalPath")
        if not path:
            continue
        detail, posted, desc = None, p.get("postedOn"), None
        try:
            d = requests.get(f"https://{host}/wday/cxs/{tenant}/{site}{path}",
                             headers=UA, timeout=TIMEOUT)
            if d.ok:
                detail = d.json().get("jobPostingInfo", {})
        except Exception:
            pass
        if detail:
            desc = _clean_html(detail.get("jobDescription"))
            posted = detail.get("postedOn") or posted
        out.append({
            "company": co["name"], "title": p.get("title"),
            "location": (detail or {}).get("location") or p.get("locationsText"),
            "url": f"https://{host}/en-US/{site}{path}",
            "posted_date": posted, "description": desc,
        })
    return out, True, inventory


def fetch_google_careers(co, query):
    try:
        r = requests.get(co["url"], headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
    except Exception:
        return [], False, None
    out = []
    for j in jobs:
        out.append({
            "company": co["name"], "title": j.get("title"),
            "location": "; ".join(l.get("display", "") for l in j.get("locations", [])) or None,
            "url": j.get("apply_url") or f"https://careers.google.com/jobs/results/{j.get('id','')}",
            "posted_date": j.get("publish_date"),
            "description": _clean_html(j.get("description")),
        })
    return out, True, None


def fetch_oracle_orc(co, query):
    base = co["url"].rstrip("/")
    site = co["site_number"]
    # ORC quirk: keyword search needs expand=all or requisitionList comes back
    # empty; "unifier" fuzzy-matches the whole site, so search a configured
    # tighter term and let the pipeline's keyword filter do the real work.
    q = co.get("search_query", query)
    finder = f'findReqs;siteNumber={site},keyword={q},limit=25'
    try:
        r = requests.get(base, params={"onlyData": "true", "expand": "all",
                                       "finder": finder},
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json().get("items", [])
        reqs = items[0].get("requisitionList", []) if items else []
    except Exception:
        return [], False, None
    out = []
    for q in reqs:
        rid = q.get("Id")
        desc = None
        try:
            d = requests.get(base.replace("recruitingCEJobRequisitions",
                                          "recruitingCEJobRequisitionDetails"),
                             params={"onlyData": "true",
                                     "finder": f'ById;Id="{rid}",siteNumber={site}'},
                             headers=UA, timeout=TIMEOUT)
            if d.ok:
                di = d.json().get("items", [])
                if di:
                    desc = _clean_html(di[0].get("ExternalDescriptionStr"))
        except Exception:
            pass
        out.append({
            "company": co["name"], "title": q.get("Title"),
            "location": q.get("PrimaryLocation"),
            "url": f"https://careers.oracle.com/jobs/#en/sites/jobsearch/job/{rid}",
            "posted_date": q.get("PostedDate"), "description": desc,
        })
    return out, True, None


def fetch_greenhouse(co, query):
    board = co["greenhouse_board"]
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                         params={"content": "true"}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
    except Exception:
        return [], False, None
    out = []
    for j in jobs:
        desc = _clean_html(j.get("content"))
        blob = f"{j.get('title','')}\n{desc or ''}".casefold()
        if query.casefold() not in blob:
            continue
        out.append({
            "company": co["name"], "title": j.get("title"),
            "location": (j.get("location") or {}).get("name"),
            "url": j.get("absolute_url"),
            "posted_date": j.get("first_published") or j.get("updated_at"),
            "description": desc,
        })
    return out, True, len(jobs)


def fetch_generic_page(co, query):
    """Keyword presence check only. Hits become triage entries — the agent
    extracts the real posting; the script never guesses page structure."""
    try:
        r = requests.get(co["url"], headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        # raw source, not rendered text: JS-app career sites carry job data in
        # embedded script JSON that get_text() would strip
        text = r.text.casefold()
    except Exception:
        return [], False, None
    if query.casefold() in text:
        return [{"triage": True, "company": co["name"], "title": None,
                 "url": co["url"],
                 "note": f'careers page mentions "{query}" — extract the actual posting'}], True, None
    return [], True, None


def fetch_jsearch(queries):
    key = os.environ.get("JSEARCH_API_KEY")
    if not key:
        return [], None
    out, ok = [], True
    for q in queries:
        try:
            r = requests.get("https://jsearch.p.rapidapi.com/search",
                             params={"query": q, "country": "us", "num_pages": 1},
                             headers={"X-RapidAPI-Key": key,
                                      "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
                             timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json().get("data", []):
                loc = ", ".join(x for x in [j.get("job_city"), j.get("job_state")] if x) or \
                      j.get("job_country")
                comp = None
                if j.get("job_min_salary") and j.get("job_max_salary"):
                    comp = (f"${j['job_min_salary']:,.0f} - ${j['job_max_salary']:,.0f} "
                            f"per {j.get('job_salary_period', 'year').lower()}")
                direct_links = [o.get("apply_link") for o in j.get("apply_options", [])
                                if o.get("is_direct")]
                out.append({
                    "company": j.get("employer_name"), "title": j.get("job_title"),
                    "location": loc,
                    "url": (direct_links[0] if direct_links else j.get("job_apply_link")),
                    "direct_link": bool(direct_links),
                    "posted_date": j.get("job_posted_at_datetime_utc"),
                    "comp": comp, "description": j.get("job_description"),
                    "country": j.get("job_country"),
                })
        except Exception:
            ok = False
    return out, ok


def fetch_adzuna(queries):
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return [], None
    out, ok = [], True
    for q in queries:
        try:
            r = requests.get("https://api.adzuna.com/v1/api/jobs/us/search/1",
                             params={"app_id": app_id, "app_key": app_key,
                                     "what_phrase": q.strip('"'), "max_days_old": 90,
                                     "results_per_page": 50},
                             headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json().get("results", []):
                comp = None
                if str(j.get("salary_is_predicted")) == "0" and j.get("salary_min"):
                    hi = j.get("salary_max") or j["salary_min"]
                    comp = f"${j['salary_min']:,.0f} - ${hi:,.0f}"
                out.append({
                    "company": (j.get("company") or {}).get("display_name"),
                    "title": j.get("title"),
                    "location": (j.get("location") or {}).get("display_name"),
                    "url": j.get("redirect_url"), "posted_date": j.get("created"),
                    "comp": comp, "description": j.get("description"),
                    "country": "US",
                })
        except Exception:
            ok = False
    return out, ok


def fetch_jooble(queries):
    key = os.environ.get("JOOBLE_API_KEY")
    if not key:
        return [], None
    out, ok = [], True
    for q in queries:
        try:
            r = requests.post(f"https://jooble.org/api/{key}",
                              json={"keywords": q.strip('"'), "location": "USA"},
                              timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                out.append({
                    "company": j.get("company"), "title": j.get("title"),
                    "location": j.get("location"), "url": j.get("link"),
                    "posted_date": j.get("updated"),
                    "comp": (j.get("salary") or None),
                    "description": _clean_html(j.get("snippet")),
                    "country": "US",
                })
        except Exception:
            ok = False
    return out, ok


def fetch_meta_graphql(co, query):
    """Meta careers CPJobSearchSourceQuery — shape captured from live site
    2026-07-17. lsd token is per-pagefetch; doc_id is long-lived."""
    doc_id = co.get("doc_id", "27807005005556827")
    s = requests.Session()
    s.headers["User-Agent"] = UA["User-Agent"]
    try:
        p = s.get("https://www.metacareers.com/jobs", timeout=TIMEOUT)
        lsd = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', p.text).group(1)
    except Exception:
        return [], False, None
    jazoest = "2" + str(sum(ord(c) for c in lsd))

    def search(q):
        r = s.post("https://www.metacareers.com/graphql", data={
            "av": "0", "__user": "0", "__a": "1", "__comet_req": "31", "lsd": lsd,
            "jazoest": jazoest, "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": "CPJobSearchSourceQuery",
            "variables": json.dumps({"search_input": {"q": q, "results_per_page": "FIVE"}}),
            "server_timestamps": "true", "doc_id": doc_id},
            headers={"x-fb-lsd": lsd,
                     "Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT)
        body = r.text[9:] if r.text.startswith("for (;;);") else r.text
        d = json.loads(body).get("data") or {}
        js = d.get("job_search_with_featured_jobs_v2") or \
            d.get("job_search_with_featured_jobs") or {}
        return js.get("all_jobs")

    out, seen = [], set()
    ok = True
    try:
        # Meta pads empty searches with "featured jobs" filler; anything that
        # also comes back for a nonsense query is noise, not a keyword match.
        noise = {j.get("id") for j in (search("zzqxvwy999") or [])}
        for q in (query, "Primavera"):
            for j in search(q) or []:
                jid = j.get("id")
                if not jid or jid in seen or jid in noise:
                    continue
                seen.add(jid)
                out.append({
                    "company": co["name"], "title": j.get("title"),
                    "location": "; ".join(j.get("locations") or []) or None,
                    "url": f"https://www.metacareers.com/jobs/{jid}/",
                    "posted_date": None, "description": None,
                    "search_matched": True,
                })
        inventory = len(search("engineer") or [])  # aliveness: common term
    except Exception:
        return out, False, None
    return out, ok, inventory


def fetch_avature_feed(co, query):
    """Avature keyword-search RSS feed (e.g. Deloitte). Detail pages are
    server-rendered; description text pulled from the posting page."""
    try:
        r = requests.get(co["feed_url"], headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        items = re.findall(r"<item>(.*?)</item>", r.text, re.S)
    except Exception:
        return [], False, None
    out = []
    for it in items:
        def tag(name):
            m = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", it, re.S)
            return html.unescape(m.group(1).strip()) if m else None
        link = tag("link")
        if not link:
            continue
        desc = None
        try:
            d = requests.get(link, headers=UA, timeout=TIMEOUT)
            if d.ok:
                soup = BeautifulSoup(d.text, "html.parser")
                node = soup.select_one(
                    ".jobDescription, .job-description, .article__content, "
                    "[class*=jobDetail], main") or soup.body
                if node:
                    desc = re.sub(r"\n{3,}", "\n\n", node.get_text("\n")).strip() or None
        except Exception:
            pass
        out.append({
            "company": co["name"], "title": tag("title"), "location": tag("location"),
            "url": link, "posted_date": tag("pubDate"), "description": desc,
        })
    return out, True, None


def fetch_phenom(co, query):
    """Phenom People careers sites (e.g. Bechtel): refineSearch widget for
    matches + jobDetail widget for full descriptions."""
    host = co["phenom_host"]

    def widgets(payload):
        r = requests.post(f"https://{host}/widgets", json=payload,
                          headers={**UA, "Content-Type": "application/json"},
                          timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    base = {"lang": "en_us", "deviceType": "desktop", "country": "us",
            "siteType": "external"}
    try:
        d = widgets({**base, "pageName": "search-results", "ddoKey": "refineSearch",
                     "sortBy": "", "subsearch": "", "from": 0, "jobs": True,
                     "counts": True, "all_fields": [], "size": 50, "clearAll": False,
                     "jdsource": "facets", "isSliderEnable": False, "pageId": "page12",
                     "keywords": query, "global": True})
        jobs = d.get("refineSearch", {}).get("data", {}).get("jobs", [])
    except Exception:
        return [], False, None
    out = []
    for j in jobs:
        desc = None
        try:
            det = widgets({**base, "pageName": "job-details", "ddoKey": "jobDetail",
                           "jobId": str(j.get("jobId")),
                           "jobSeqNo": j.get("jobSeqNo"), "pageId": "page14"})
            job = (det.get("jobDetail", {}).get("data") or {}).get("job", {})
            desc = _clean_html(job.get("description"))
        except Exception:
            pass
        out.append({
            "company": co["name"], "title": j.get("title"),
            "location": j.get("cityStateCountry") or j.get("location"),
            "url": j.get("applyUrl") or f"https://{host}/job/{j.get('jobId')}",
            "posted_date": j.get("dateCreated"),
            "description": desc or j.get("descriptionTeaser"),
        })
    inventory = None
    try:
        inv = widgets({**base, "pageName": "search-results", "ddoKey": "refineSearch",
                       "sortBy": "", "subsearch": "", "from": 0, "jobs": False,
                       "counts": True, "all_fields": [], "size": 1, "clearAll": False,
                       "jdsource": "facets", "isSliderEnable": False, "pageId": "page12",
                       "keywords": "", "global": True})
        inventory = inv.get("refineSearch", {}).get("totalHits")
    except Exception:
        pass
    return out, True, inventory


DIRECT_ADAPTERS = {
    "workday": fetch_workday,
    "google_careers": fetch_google_careers,
    "oracle_orc": fetch_oracle_orc,
    "greenhouse": fetch_greenhouse,
    "generic_page": fetch_generic_page,
    "meta_graphql": fetch_meta_graphql,
    "avature_feed": fetch_avature_feed,
    "phenom": fetch_phenom,
}
