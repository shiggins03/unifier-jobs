"""Daily pipeline: fetch → filter → resolve → dedup → expire → health → publish.
Run from repo root: python -m scraper.main"""
import datetime as dt
import re
from pathlib import Path

import yaml

from . import models, sources, site_gen
from .filters import (blocklisted, extract_stated_comp, is_non_us, keyword_tier,
                      title_match)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
BOARD_MAX_AGE_DAYS = 90
GONE_AFTER_MISSES_DIRECT = 2
GONE_AFTER_MISSES_BOARD = 7
LONG_POSTED_DAYS = 90


def load_yaml(name):
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def parse_date(s):
    """Best-effort parse of machine dates for classification only (age cutoffs,
    long-posted flag). Unparseable human strings ('Posted 3 Days Ago') -> None;
    display always shows the verbatim string regardless."""
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def roster_match(company, roster_norms):
    c = models.norm(company)
    if not c:
        return None
    for rn, entry in roster_norms.items():
        if rn in c or c in rn:
            return entry
    return None


def run():
    today = dt.date.today().isoformat()
    companies = load_yaml("companies.yaml")["companies"]
    kw = load_yaml("keywords.yaml")
    bl = load_yaml("blocklist.yaml")
    cities = load_yaml("cities.yaml")

    store = models.load_jobs()
    baseline = not store
    for j in store.values():
        j["flags"] = [f for f in j["flags"] if f != "new"]

    triage = models.load_json(models.TRIAGE, [])
    triage_keys = {(t.get("company"), t.get("url")) for t in triage}
    health = models.load_json(models.HEALTH, {})
    roster_norms = {models.norm(c["name"]): c for c in companies}
    query = kw["tier1"][0]

    def record_health(name, count, ok, inventory=None):
        h = health.setdefault(name, {"counts": [], "fail_streak": 0})
        if ok:
            h["counts"] = (h["counts"] + [count])[-5:]
            h["fail_streak"] = 0
        else:
            h["fail_streak"] += 1
        if inventory is not None:
            h["inventory"] = inventory  # source's total visible jobs (aliveness)
        h["last_run"] = today

    def add_triage(company, url, note, source):
        if (company, url) not in triage_keys:
            triage.append({"company": company, "url": url, "note": note,
                           "source": source, "first_seen": today})
            triage_keys.add((company, url))

    seen_this_run = {}  # source name -> set of job ids seen
    sources_ok = set()

    # ---- direct monitors ----
    for co in companies:
        if not co.get("enabled"):
            continue
        adapter = sources.DIRECT_ADAPTERS.get(co["ats"])
        if not adapter:
            continue
        records, ok, inventory = adapter(co, query)
        src = f"{co['ats']}:{co['name']}"
        listings = 0
        if ok:
            sources_ok.add(src)
        for r in records:
            if r.get("triage"):
                add_triage(r["company"], r["url"], r["note"], src)
                listings += 1
                continue
            if is_non_us(r.get("location")):
                continue
            tier = keyword_tier(r.get("title"), r.get("description"), kw)
            if tier is None:
                if r.get("search_matched"):
                    add_triage(r["company"], r["url"],
                               f"employer's own search matched '{query}' but posting "
                               f"text unavailable — verify: {r.get('title')}", src)
                continue
            comp = r.get("comp") or extract_stated_comp(r.get("description"))
            job = models.make_job(
                source=src, kind="direct", company=r["company"], title=r["title"],
                location=r.get("location"), url=r["url"],
                posted_date=r.get("posted_date"), comp=comp,
                description=r.get("description"), tier=tier, today=today)
            if tier == 1 and title_match(r.get("title"), kw):
                job["flags"].append("title-match")
            _merge(store, job, today, baseline)
            seen_this_run.setdefault(src, set()).add(job["id"])
            listings += 1
        record_health(src, listings, ok, inventory)

    # ---- discovery boards ----
    board_batches = [("jsearch", sources.fetch_jsearch(kw["discovery_queries"])),
                     ("adzuna", sources.fetch_adzuna(kw["discovery_queries"])),
                     ("jooble", sources.fetch_jooble(kw["discovery_queries"]))]
    for name, (records, ok) in board_batches:
        if ok is None:
            continue  # no API key configured; silently skipped
        if ok:
            sources_ok.add(name)
        kept = 0
        for r in records:
            company, title = r.get("company"), r.get("title")
            if not (company and title and r.get("url")):
                continue
            country = (r.get("country") or "").upper()
            if country and country not in ("US", "USA", "UNITED STATES"):
                continue
            if is_non_us(r.get("location")):
                continue
            reason = blocklisted(company, title, bl)
            if reason:
                models.append_quarantine({"company": company, "title": title,
                                          "url": r["url"], "reason": reason,
                                          "source": name, "date": today})
                continue
            tier = keyword_tier(title, r.get("description"), kw)
            if tier is None:
                continue
            posted = parse_date(r.get("posted_date"))
            if posted and (dt.date.today() - posted).days > BOARD_MAX_AGE_DAYS:
                continue
            entry = roster_match(company, roster_norms)
            if entry and entry.get("enabled"):
                continue  # direct monitor is authoritative; drop board copy
            if entry:
                add_triage(company, r["url"],
                           "roster company not yet fingerprinted — verify ATS endpoint",
                           name)
            else:
                add_triage(company, r["url"],
                           "unknown employer — find direct posting, propose tier", name)
            comp = r.get("comp") or extract_stated_comp(r.get("description"))
            job = models.make_job(
                source=name, kind="board", company=company, title=title,
                location=r.get("location"), url=r["url"],
                posted_date=r.get("posted_date"), comp=comp,
                description=r.get("description"), tier=tier, today=today)
            _merge(store, job, today, baseline)
            seen_this_run.setdefault(name, set()).add(job["id"])
            kept += 1
        record_health(name, kept, ok)

    # ---- expiry ----
    for j in store.values():
        if j["status"] != "active":
            continue
        src = j["source"]
        ran = src in sources_ok
        seen = j["id"] in seen_this_run.get(src, set())
        if ran and not seen:
            j["miss_count"] += 1
            limit = (GONE_AFTER_MISSES_DIRECT if j["kind"] == "direct"
                     else GONE_AFTER_MISSES_BOARD)
            if j["miss_count"] >= limit:
                j["status"] = "gone"
                j["gone_date"] = today
        posted = parse_date(j.get("posted_date"))
        if posted:
            age = (dt.date.today() - posted).days
            if age > LONG_POSTED_DAYS and "long-posted" not in j["flags"]:
                j["flags"].append("long-posted")
            if j["kind"] == "board" and age > BOARD_MAX_AGE_DAYS + 30:
                j["status"] = "gone"
                j["gone_date"] = j["gone_date"] or today

    # ---- health warnings ----
    warnings = []
    for name, h in health.items():
        if name.startswith("_"):
            continue
        if h.get("fail_streak", 0) >= 3:
            warnings.append(f"{name}: fetch failing ({h['fail_streak']} runs)")
        elif h.get("inventory") == 0:
            warnings.append(f"{name}: source reports 0 total jobs — monitor may be "
                            f"blind or endpoint changed")
        elif len(h.get("counts", [])) >= 3 and all(c == 0 for c in h["counts"][-3:]) \
                and any(c > 0 for c in h["counts"][:-3]):
            warnings.append(f"{name}: zero results for 3+ runs (was returning data)")
    health["_warnings"] = warnings

    models.save_jobs(store)
    models.save_json(models.TRIAGE, triage)
    models.save_json(models.HEALTH, health)
    # Compact single-file feed for the artifact: MCP connector responses are
    # size-capped, so descriptions are truncated here (flagged, link has full
    # text). The Pages dashboard keeps complete descriptions.
    DESC_CAP = 2000
    feed_jobs = []
    for j in sorted(store.values(), key=lambda x: x["status"] != "active"):
        fj = {k: j[k] for k in ("id", "kind", "company", "title", "location", "url",
                                "posted_date", "comp", "tier", "status", "gone_date",
                                "flags")}
        desc = j.get("description")
        if desc and len(desc) > DESC_CAP:
            fj["description"] = desc[:DESC_CAP]
            fj["desc_truncated"] = True
        else:
            fj["description"] = desc
        feed_jobs.append(fj)
    models.save_json(models.DATA / "feed.json", {
        "updated": today,
        "warnings": warnings,
        "roster": [{"name": c["name"], "tier": c["tier"], "ats": c["ats"],
                    "enabled": bool(c.get("enabled")), "note": c.get("note")}
                   for c in companies],
        "triage": [t for t in triage if not t.get("status")],
        "jobs": feed_jobs,
    })
    site_gen.generate(store, companies, cities, warnings, today)

    active = sum(1 for j in store.values() if j["status"] == "active")
    new = sum(1 for j in store.values() if "new" in j["flags"])
    print(f"run complete: {active} active listings, {new} new, "
          f"{len(triage)} in triage queue, {len(warnings)} health warnings"
          + (" [baseline run]" if baseline else ""))


def _merge(store, job, today, baseline):
    old = store.get(job["id"])
    if old:
        old["last_seen"] = today
        old["miss_count"] = 0
        if old["status"] == "gone":
            old["status"] = "active"
            old["gone_date"] = None
        if old["kind"] == "board" and job["kind"] == "direct":
            keep_first_seen = old["first_seen"]
            store[job["id"]] = job
            job["first_seen"] = keep_first_seen
            return
        for f in ("posted_date", "comp", "description", "url", "location"):
            if job.get(f):
                old[f] = job[f]
        if "title-match" in job["flags"] and "title-match" not in old["flags"]:
            old["flags"].append("title-match")
    else:
        if not baseline:
            job["flags"].append("new")
        store[job["id"]] = job


if __name__ == "__main__":
    run()
