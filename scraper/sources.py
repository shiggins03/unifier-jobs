"""Source adapters. Direct ATS adapters return structured listings; generic_page
returns triage entries (the script never parses arbitrary page structure).
Discovery adapters skip silently when their API key isn't configured.
Direct adapters return (records, ok, inventory): inventory is the source's TOTAL
visible job count regardless of keyword (aliveness check — 0 or None-when-expected
means the monitor may be blind, not that no jobs match). Discovery adapters
return (records, ok)."""
import html
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
    finder = f'findReqs;siteNumber={site},keyword="{query}",limit=25'
    try:
        r = requests.get(base, params={"onlyData": "true", "finder": finder},
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


DIRECT_ADAPTERS = {
    "workday": fetch_workday,
    "google_careers": fetch_google_careers,
    "oracle_orc": fetch_oracle_orc,
    "greenhouse": fetch_greenhouse,
    "generic_page": fetch_generic_page,
}
