"""Daily pipeline: fetch → filter → resolve → dedup → expire → health → publish.
Run from repo root: python -m scraper.main"""
import datetime as dt
import re
from pathlib import Path

import yaml

from . import models, sources, site_gen
from .filters import (blocklisted, city_rank, classify_role, extract_stated_comp,
                      is_non_us, keyword_tier, title_match)

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
    roles = load_yaml("roles.yaml")
    # Hand-copied comp for postings that render their pay client-side (Meta).
    # Fills an EMPTY comp only — never overrides what a feed reported.
    comp_overrides = (load_yaml("comp_overrides.yaml") or {}).get("overrides") or []

    def comp_override_for(url):
        for o in comp_overrides:
            frag, val = o.get("url_contains"), o.get("comp")
            if frag and val and frag in (url or ""):
                return val
        return None

    store = models.load_jobs()
    baseline = not store
    # Scope (US + remote only) is a hard rule, so it applies to the whole
    # store, not just today's fetch: when the non-US filter is tightened,
    # already-stored postings that are now out of scope drop immediately
    # instead of lingering two runs until they age out as "gone" — which
    # would also mislabel them, since they are still listed, just not for us.
    dropped_scope = [k for k, j in store.items() if is_non_us(j.get("location"))]
    for k in dropped_scope:
        del store[k]
    # Same reasoning for keyword scope: tier 2 (P6/OPC/PIF/OIC) was removed
    # 2026-08-07, so stored tier-2 postings leave the board immediately rather
    # than lingering until they age out as "gone" — they are still listed by
    # the employer, just not relevant to this search. Keyed off the STORED
    # tier, deliberately not re-derived: a tier-1 job whose description failed
    # to fetch, or a manual seed that declared its tier, must not be purged
    # just because the text isn't re-checkable this run.
    live_tiers = {1} if not kw.get("tier2") else {1, 2}
    dropped_kw = [k for k, j in store.items() if j.get("tier") not in live_tiers]
    for k in dropped_kw:
        del store[k]
    for j in store.values():
        j["flags"] = [f for f in j["flags"] if f != "new"]
    # Derived tags are recomputed across the WHOLE store every run, not just
    # for postings seen today: otherwise adding or tuning roles.yaml never
    # reaches the jobs already stored, and sources that fail for a day would
    # leave their jobs untagged.
    for j in store.values():
        j["role"] = classify_role(j.get("title"), j.get("description"), roles)

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
            hand_comp = None if comp else comp_override_for(r.get("url"))
            job = models.make_job(
                source=src, kind="direct", company=r["company"], title=r["title"],
                location=r.get("location"), url=r["url"],
                posted_date=r.get("posted_date"), comp=comp or hand_comp,
                description=r.get("description"), tier=tier, today=today)
            job["role"] = classify_role(r.get("title"), r.get("description"), roles)
            if hand_comp:
                job["flags"].append("comp-manual")
            if tier == 1 and title_match(r.get("title"), kw):
                job["flags"].append("title-match")
            _merge(store, job, today, baseline)
            seen_this_run.setdefault(src, set()).add(job["id"])
            listings += 1
        record_health(src, listings, ok, inventory)

    # ---- manually seeded postings ----
    # Escape hatch for employers whose sites refuse automated clients (MTA and
    # friends). Fields are human-copied verbatim per hard rule #1, so they are
    # trusted as-is; the keyword filter still decides tier unless the entry
    # states one (needed when no description could be copied).
    for r in (load_yaml("seed_jobs.yaml") or {}).get("jobs") or []:
        if not (r.get("url") and r.get("company") and r.get("title")):
            continue
        src = f"seed:{r['company']}"
        sources_ok.add(src)
        if is_non_us(r.get("location")):
            continue
        tier = keyword_tier(r.get("title"), r.get("description"), kw) or r.get("tier")
        if tier not in (1, 2):
            continue
        job = models.make_job(
            source=src, kind="direct", company=r["company"], title=r["title"],
            location=r.get("location"), url=r["url"],
            posted_date=r.get("posted_date"), comp=r.get("comp"),
            description=r.get("description"), tier=tier, today=today)
        job["flags"].append("manual")
        job["role"] = classify_role(r.get("title"), r.get("description"), roles)
        if tier == 1 and title_match(r.get("title"), kw):
            job["flags"].append("title-match")
        _merge(store, job, today, baseline)
        seen_this_run.setdefault(src, set()).add(job["id"])
        record_health(src, 1, True)

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
        # Aggregators syndicate one posting once per city — Adzuna returned
        # Oracle's "Senior Principal Consultant" ~10 times (Madison,
        # Providence, Atlanta, Pierre...). Job ids hash location, so those
        # would land as distinct cards. Collapse on company+title and keep
        # the best-ranked location, since an aggregator hit is discovery
        # anyway (rule #4) and resolves to one employer posting.
        seen_ct, deduped = {}, []
        for r in records:
            k = (models.norm(r.get("company")), models.norm(r.get("title")))
            prev = seen_ct.get(k)
            if prev is None:
                seen_ct[k] = len(deduped)
                deduped.append(r)
            elif (city_rank(r.get("location"), cities)
                  < city_rank(deduped[prev].get("location"), cities)):
                deduped[prev] = r  # nearer metro wins
        if len(deduped) != len(records):
            print(f"  {name}: collapsed {len(records)} -> {len(deduped)} "
                  f"(same job listed per-city)")
        for r in deduped:
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
            job["role"] = classify_role(title, r.get("description"), roles)
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
    # Artifact feed: MCP connector replies have a size ceiling (large files
    # hang and die at the ~130s reply budget), so the feed is a tiny index
    # and each description is its own small file fetched on demand when a
    # card is expanded. The Pages dashboard keeps complete descriptions.
    DESC_CAP = 2000
    descs_dir = models.DATA / "descs"
    if descs_dir.exists():
        for f in descs_dir.glob("*.txt"):
            f.unlink()
    descs_dir.mkdir(exist_ok=True)
    feed_jobs = []
    for j in sorted(store.values(), key=lambda x: x["status"] != "active"):
        fj = {k: j[k] for k in ("id", "kind", "company", "title", "location", "url",
                                "posted_date", "comp", "tier", "status", "gone_date",
                                "flags")}
        fj["role"] = j.get("role")   # derived filter tag, not a stated fact
        desc = j.get("description")
        if desc and j["status"] == "active":
            fj["has_desc"] = True
            out_text = desc[:DESC_CAP]
            if len(desc) > DESC_CAP:
                out_text += "\n\n[Truncated for this view — full text at the posting link]"
            (descs_dir / f"{j['id']}.txt").write_text(out_text, encoding="utf-8")
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
          + (f", {len(dropped_scope)} dropped as out-of-scope" if dropped_scope else "")
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
        # Derived tags must refresh on every run, not just for new jobs —
        # otherwise tuning roles.yaml (or adding the classifier at all) never
        # reaches the ~all postings that already exist in the store.
        old["role"] = job.get("role")
        # Derived flags must follow their field onto the stored record,
        # otherwise a re-run keeps the value but loses its provenance badge.
        for f in ("title-match", "comp-manual"):
            if f in job["flags"] and f not in old["flags"]:
                old["flags"].append(f)
        if "comp-manual" not in job["flags"] and "comp-manual" in old["flags"]:
            old["flags"].remove("comp-manual")   # employer started stating it
    else:
        if not baseline:
            job["flags"].append("new")
        store[job["id"]] = job


if __name__ == "__main__":
    run()
