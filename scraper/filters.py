"""Keyword tiers, US scope, spam blocklist, comp extraction.
Comp extraction quotes the posting's exact text — it never computes a value."""
import re

NON_US = re.compile(
    r"\b(india|united kingdom|\buk\b|london|dubai|abu dhabi|uae|saudi|riyadh|qatar|doha|"
    r"canada|toronto|vancouver|ontario|australia|sydney|melbourne|singapore|philippines|"
    r"malaysia|hyderabad|bangalore|bengaluru|chennai|mumbai|pune|noida|gurgaon|delhi|"
    r"ireland|dublin|germany|poland|romania|mexico|\bmx\b|brazil|colombia|"
    r"argentina|buenos aires|chile|peru|santiago)\b", re.I)

COMP_RE = re.compile(
    r"(?:salary|pay|compensation|range|rate)[^.\n]{0,80}?"
    r"(\$[\d,]+(?:\.\d+)?(?:\s*[-–to]+\s*\$?[\d,]+(?:\.\d+)?)?"
    r"(?:\s*(?:/|per\s*)?(?:year|yr|hour|hr|annum|annually|hourly))?"
    r"[^.\n]{0,120}?(?:bonus|equity)?[^.\n]{0,40})", re.I)
DOLLAR_RANGE_RE = re.compile(
    r"\$[\d,]{4,}(?:\.\d+)?\s*(?:[-–]|to)\s*\$?[\d,]{4,}(?:\.\d+)?"
    r"(?:\s*(?:/|per\s*)?(?:year|yr|hour|hr|annum|annually|hourly))?", re.I)
SALARY_NUM_RE = re.compile(r"\$?([\d,]+(?:\.\d+)?)")


def title_match(title, kw):
    low = (title or "").casefold()
    return any(re.search(rf"\b{re.escape(t.casefold())}\b", low) for t in kw["tier1"])


def keyword_tier(title, body, kw):
    text = f"{title or ''}\n{body or ''}"
    low = text.casefold()
    for t in kw["tier1"]:
        if re.search(rf"\b{re.escape(t.casefold())}\b", low):
            return 1
    ctx = any(c.casefold() in low for c in kw["tier2"]["context_required"])
    if ctx:
        for t in kw["tier2"]["tokens"]:
            if re.search(rf"\b{re.escape(t)}\b", text):  # case-sensitive: P6 not p6-ish words
                return 2
    return None


def is_non_us(location):
    return bool(location and NON_US.search(location))


def blocklisted(company, title, bl):
    c = (company or "").casefold()
    for b in bl.get("companies", []):
        if b.casefold() in c:
            return f"blocklisted company: {b}"
    t = (title or "").casefold()
    for p in bl.get("title_patterns", []):
        if p.casefold() in t:
            return f"title pattern: {p}"
    return None


def extract_stated_comp(description):
    """Return the posting's own compensation sentence fragment, verbatim, or None."""
    if not description:
        return None
    m = COMP_RE.search(description)
    if m:
        return m.group(0).strip()
    m = DOLLAR_RANGE_RE.search(description)
    if m:
        return m.group(0).strip()
    return None


def comp_sort_value(comp):
    """Numeric value for ORDERING only — display always shows the verbatim string."""
    if not comp:
        return -1.0
    nums = [float(n.replace(",", "")) for n in SALARY_NUM_RE.findall(comp)
            if n.replace(",", "").replace(".", "").isdigit()]
    nums = [n for n in nums if n >= 20]  # ignore stray small numbers
    if not nums:
        return -1.0
    v = max(nums)
    if v < 1000:  # stated hourly rate; annualize for ordering only
        v *= 2080
    return v


def city_rank(location, cities):
    if not location:
        return cities["other_us_rank"]
    low = location.casefold()
    if "remote" in low:
        return cities["remote_rank"]
    for m in cities["metros"]:
        if any(term in low for term in m["match"]):
            return m["rank"]
    return cities["other_us_rank"]
