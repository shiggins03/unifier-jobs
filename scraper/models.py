"""Job record store. Everything displayed comes verbatim from the source;
fields the source didn't state are None, never inferred."""
import hashlib
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
JOBS = DATA / "jobs.jsonl"
TRIAGE = DATA / "needs_triage.json"
QUARANTINE = DATA / "quarantine.jsonl"
HEALTH = DATA / "health.json"


def norm(s):
    return re.sub(r"\s+", " ", (s or "").casefold().strip())


def job_id(company, title, location):
    key = f"{norm(company)}|{norm(title)}|{norm(location)}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def make_job(*, source, kind, company, title, location=None, url,
             posted_date=None, comp=None, description=None, tier, today):
    return {
        "id": job_id(company, title, location or ""),
        "source": source,
        "kind": kind,  # "direct" | "board"
        "company": company,
        "title": title,
        "location": location,
        "url": url,
        "posted_date": posted_date,  # verbatim string from source, or None
        "comp": comp,                # verbatim string from source, or None
        "description": description,
        "tier": tier,                # 1 = Unifier, 2 = context-backed P6/OPC/PIF/OIC
        "first_seen": today,
        "last_seen": today,
        "status": "active",
        "gone_date": None,
        "miss_count": 0,
        "flags": [],
    }


def load_jobs():
    if not JOBS.exists():
        return {}
    out = {}
    for line in JOBS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            j = json.loads(line)
            out[j["id"]] = j
    return out


def save_jobs(jobs):
    DATA.mkdir(exist_ok=True)
    with JOBS.open("w", encoding="utf-8") as f:
        for j in jobs.values():
            f.write(json.dumps(j, ensure_ascii=False) + "\n")


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, obj):
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def append_quarantine(entry):
    DATA.mkdir(exist_ok=True)
    with QUARANTINE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
