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
    # limit must exceed the match count or qualifying reqs get truncated:
    # 2026-07-18 the ONE unifier-mentioning req was #26+ of 27 and limit=25
    # silently dropped it every run.
    finder = f'findReqs;siteNumber={site},keyword={q},limit=100'
    try:
        r = requests.get(base, params={"onlyData": "true", "expand": "all",
                                       "finder": finder},
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json().get("items", [])
        reqs = items[0].get("requisitionList", []) if items else []
        inventory = items[0].get("TotalJobsCount") if items else None
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
        job_base = co.get("job_url_base",
                          "https://careers.oracle.com/jobs/#en/sites/jobsearch/job")
        out.append({
            "company": co["name"], "title": q.get("Title"),
            "location": q.get("PrimaryLocation"),
            "url": f"{job_base}/{rid}",
            "posted_date": q.get("PostedDate"), "description": desc,
            # desc fetched → tier filter's call is final; desc missing → the
            # filter is blind, surface as triage instead of dropping silently
            "search_matched": desc is None,
        })
    return out, True, inventory


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
    extracts the real posting; the script never guesses page structure.
    Optional check_pattern (regex) replaces the plain keyword check for
    search pages that echo the query into their own HTML (e.g. match the
    keyword inside a job-URL slug instead)."""
    try:
        r = requests.get(co["url"], headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        # raw source, not rendered text: JS-app career sites carry job data in
        # embedded script JSON that get_text() would strip
        text = r.text.casefold()
    except Exception:
        return [], False, None
    pattern = co.get("check_pattern")
    if (re.search(pattern, r.text, re.I) if pattern else query.casefold() in text):
        return [{"triage": True, "company": co["name"], "title": None,
                 "url": co["url"],
                 "note": f'careers page mentions "{query}" — extract the actual posting'}], True, None
    return [], True, None


def fetch_amazon_jobs(co, query):
    """amazon.jobs public search JSON. Full-text over the posting body, and a
    nonsense query returns 0 hits (verified 2026-07-30), so no echo guard is
    needed. Covers AWS/GES data-center construction roles."""
    out, seen = [], set()
    for q in (query, "Primavera"):
        try:
            r = requests.get("https://www.amazon.jobs/en/search.json",
                             params={"base_query": q, "result_limit": 100,
                                     "country": "USA"},
                             headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            jobs = r.json().get("jobs", [])
        except Exception:
            return out, False, None
        for j in jobs:
            path = j.get("job_path")
            if not path or path in seen:
                continue
            seen.add(path)
            desc = "\n\n".join(_clean_html(j.get(k)) or "" for k in
                               ("description", "basic_qualifications",
                                "preferred_qualifications")).strip() or None
            loc = j.get("location") or ", ".join(
                x for x in [j.get("city"), j.get("state")] if x) or None
            out.append({
                "company": co["name"], "title": j.get("title"),
                "location": loc,
                "url": f"https://www.amazon.jobs{path}",
                "posted_date": j.get("posted_date"), "description": desc,
                "search_matched": desc is None,
            })
    inventory = None
    try:
        inv = requests.get("https://www.amazon.jobs/en/search.json",
                           params={"base_query": "", "result_limit": 1},
                           headers=UA, timeout=TIMEOUT)
        if inv.ok:
            inventory = inv.json().get("hits")
    except Exception:
        pass
    return out, True, inventory


def fetch_successfactors(co, query):
    """SuccessFactors Career Site Builder (e.g. Amtrak): server-rendered
    keyword search. QUIRK: a no-match search silently falls back to listing
    ALL jobs, so results only count when they differ from a nonsense query's
    results. Detail pages are server-rendered; description from .jobdescription."""
    base = co["sf_base"].rstrip("/")

    def job_links(q):
        r = requests.get(f"{base}/search/", params={"q": q}, headers=UA,
                         timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out = {}
        for a in soup.select("a.jobTitle-link[href]"):
            # location lives in a .jobLocation span in the same result row
            loc, node = None, a
            for _ in range(4):
                node = node.parent
                if node is None:
                    break
                ln = node.select_one(".jobLocation")
                if ln:
                    loc = " ".join(ln.get_text(" ").split()) or None
                    if loc:
                        break
            out[a["href"]] = (a.get_text(strip=True), loc)
        return out

    try:
        baseline = set(job_links("zzqnomatch999"))
        found = {}
        for q in (query, "Primavera"):
            found.update(job_links(q))
        if set(found) <= baseline and baseline:
            found = {}  # both searches hit the all-jobs fallback: no matches
    except Exception:
        return [], False, None
    out = []
    for href, (title, loc) in found.items():
        url = href if href.startswith("http") else base + href
        desc, posted = None, None
        try:
            d = requests.get(url, headers=UA, timeout=TIMEOUT)
            if d.ok:
                soup = BeautifulSoup(d.text, "html.parser")
                node = soup.select_one(".jobdescription, [itemprop=description]")
                if node:
                    desc = re.sub(r"\n{3,}", "\n\n",
                                  node.get_text("\n")).strip() or None
                if not loc:
                    ln = soup.select_one(".jobGeoLocation, [itemprop=address], "
                                         ".jobLocation")
                    if ln:
                        loc = " ".join(ln.get_text(" ").split()) or None
                pd = soup.select_one("[itemprop=datePosted]")
                if pd:
                    posted = pd.get_text(strip=True) or None
        except Exception:
            pass
        out.append({
            "company": co["name"], "title": title, "location": loc,
            "url": url, "posted_date": posted, "description": desc,
            "search_matched": desc is None,
        })
    inventory = len(baseline) or None  # first-page size of the all-jobs list
    return out, True, inventory


def fetch_smartrecruiters(co, query):
    """SmartRecruiters public postings API (e.g. Turner & Townsend). Search is
    server-side full-text; US scope enforced from the posting's own stated
    country code (global firms list worldwide on one board)."""
    company = co["smartrecruiters_company"]
    api = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"

    def search(q):
        r = requests.get(api, params={"q": q, "limit": 100}, headers=UA,
                         timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("content", [])

    try:
        postings = search(query) + search("Primavera")
    except Exception:
        return [], False, None
    out, seen = [], set()
    for p in postings:
        pid = p.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        loc = p.get("location") or {}
        if (loc.get("country") or "").lower() != "us":
            continue
        desc, url = None, None
        try:
            d = requests.get(f"{api}/{pid}", headers=UA, timeout=TIMEOUT)
            if d.ok:
                detail = d.json()
                secs = (detail.get("jobAd") or {}).get("sections") or {}
                desc = _clean_html("\n".join(
                    s.get("text", "") for s in secs.values()
                    if isinstance(s, dict)))
                url = detail.get("applyUrl")
        except Exception:
            pass
        out.append({
            "company": co["name"], "title": p.get("name"),
            "location": ", ".join(x for x in [
                loc.get("city"), loc.get("region"),
                (loc.get("country") or "").upper()] if x) or None,
            "url": url or f"https://jobs.smartrecruiters.com/{company}/{pid}",
            "posted_date": p.get("releasedDate"), "description": desc,
            "search_matched": desc is None,
        })
    inventory = None
    try:
        inv = requests.get(api, params={"limit": 1}, headers=UA, timeout=TIMEOUT)
        if inv.ok:
            inventory = inv.json().get("totalFound")
    except Exception:
        pass
    return out, True, inventory


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
            # Verified 2026-07-30: on RapidAPI's FREE plan /search and
            # /search-filters answer 404 "Endpoint does not exist" while
            # /job-details, /estimated-salary and /company-job-salary return
            # 200 — i.e. search is gated to a paid tier, not renamed (27 path
            # variants + POST all 404). Report unavailable rather than failing,
            # so a known-gated endpoint doesn't raise a health warning daily.
            if r.status_code == 404 and "does not exist" in r.text:
                return [], None
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


def _json_str_at(text, key, start=0):
    """Value of a JSON string field in raw page source, honouring escapes.
    Meta embeds the posting as JSON in the job_details HTML; a plain regex
    trips over the escaped quotes inside the description."""
    tag = '"%s":"' % key
    i = text.find(tag, start)
    if i < 0:
        return None
    j = i + len(tag)
    out = []
    while j < len(text):
        c = text[j]
        if c == "\\":
            out.append(text[j:j + 2])
            j += 2
            continue
        if c == '"':
            break
        out.append(c)
        j += 1
    try:
        return json.loads('"' + "".join(out) + '"')
    except Exception:
        return None


def _meta_job_detail(session, job_id):
    """Posting text + posted date for one Meta job, from the schema.org
    JobPosting JSON-LD embedded in job_details. The search API returns titles
    only, so without this every Meta posting arrives description-less and can
    never match a keyword that lives in the body — and "Unifier" is always in
    the body (their titles say "Systems Architect").

    Read the JSON-LD, never the page text: the raw page also carries a
    third-party vendor allowlist containing the literal word "unifier", which
    is what made the old page-scrape monitor fire for every query.

    NOTE: the JSON-LD has no baseSalary, and Meta renders its pay range
    ("$150,000/year to $209,000/year + bonus + equity") client-side only — it
    is in no server response, so comp stays "Not listed" for Meta.
    """
    try:
        r = session.get(
            f"https://www.metacareers.com/profile/job_details/{job_id}/",
            timeout=TIMEOUT)
        if not r.ok:
            return None, None
        t = r.text
    except Exception:
        return None, None
    # The block is a <script type="application/ld+json">, and Meta escapes the
    # "@" as @ in the raw source — so find it by tag and let json decode
    # the escapes, never by searching for the literal "@type" text.
    o = None
    for tag in BeautifulSoup(t, "html.parser").find_all(
            "script", attrs={"type": "application/ld+json"}):
        try:
            cand = json.loads(tag.string or "")
        except Exception:
            continue
        for c in (cand if isinstance(cand, list) else [cand]):
            if isinstance(c, dict) and c.get("@type") == "JobPosting":
                o = c
                break
        if o:
            break
    if o is None:
        return None, None
    parts = []
    for key in ("description", "responsibilities", "qualifications"):
        v = o.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, list):
            parts.extend(x for x in v if isinstance(x, str))
    text = _clean_html("\n".join(parts)) if parts else None
    return text, o.get("datePosted")


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
            # FIFTY, not FIVE: the search is relevance-ranked but real matches
            # are not always in the top 5, and "TWENTY" is not a valid enum
            # (it returns null). Irrelevant extras are dropped by the keyword
            # filter once their descriptions are fetched.
            "variables": json.dumps({"search_input": {"q": q, "results_per_page": "FIFTY"}}),
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
                desc, posted = _meta_job_detail(s, jid)
                out.append({
                    "company": co["name"], "title": j.get("title"),
                    "location": "; ".join(j.get("locations") or []) or None,
                    "url": f"https://www.metacareers.com/profile/job_details/{jid}/",
                    "posted_date": posted,
                    "description": desc,
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


def fetch_hrmdirect(co, query):
    """HRM Direct / ClearCompany boards (Project Partners). The company's own
    careers page just iframes this, and that iframe is why a generic_page
    monitor could never see the jobs — the outer page is byte-identical for
    every jobId. `?search=true` renders the full req table server-side.

    One req fans out into a row per location (their India posting has ~30), so
    rows are grouped by req id and the US row is preferred; the scope filter
    then drops reqs that are foreign-only."""
    host = co["hrmdirect_host"]
    try:
        r = requests.get(f"https://{host}/employment/job-openings.php",
                         params={"search": "true", "nohd": ""},
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return [], False, None

    reqs = {}
    for tr in soup.select("tr[data-req-id]"):
        req = tr.get("data-req-id")
        a = tr.select_one("td.posTitle a")
        if not (req and a):
            continue
        title = a.get_text(" ", strip=True)
        country = (tr.select_one("td.countries") or a).get_text(" ", strip=True)
        office = (tr.select_one("td.offices") or a).get_text(" ", strip=True)
        href = a.get("href") or ""
        row = {"title": title, "country": country, "office": office, "href": href}
        cur = reqs.get(req)
        if cur is None or ("united states" in country.casefold()
                           and "united states" not in cur["country"].casefold()):
            reqs[req] = row

    out = []
    for req, row in reqs.items():
        href = html.unescape(row["href"]).lstrip("/")
        url = f"https://{host}/employment/{href}" if href else \
              f"https://{host}/employment/job-opening.php?req={req}"
        desc = None
        try:
            d = requests.get(url, headers=UA, timeout=TIMEOUT)
            if d.ok:
                node = BeautifulSoup(d.text, "html.parser").body
                if node:
                    desc = re.sub(r"\n{3,}", "\n\n",
                                  node.get_text("\n", strip=True)).strip() or None
        except Exception:
            pass
        loc = ", ".join(x for x in (row["office"], row["country"]) if x) or None
        out.append({
            "company": co["name"], "title": row["title"], "location": loc,
            "url": url, "posted_date": None, "description": desc,
        })
    return out, True, len(reqs)


DIRECT_ADAPTERS = {
    "hrmdirect": fetch_hrmdirect,
    "workday": fetch_workday,
    "google_careers": fetch_google_careers,
    "oracle_orc": fetch_oracle_orc,
    "greenhouse": fetch_greenhouse,
    "generic_page": fetch_generic_page,
    "meta_graphql": fetch_meta_graphql,
    "smartrecruiters": fetch_smartrecruiters,
    "successfactors": fetch_successfactors,
    "amazon_jobs": fetch_amazon_jobs,
    "avature_feed": fetch_avature_feed,
    "phenom": fetch_phenom,
}
