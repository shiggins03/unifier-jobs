"""Keyword tiers, US scope, spam blocklist, comp extraction.
Comp extraction quotes the posting's exact text — it never computes a value."""
import re

NON_US = re.compile(
    r"\b(india|united kingdom|\buk\b|england|scotland|wales|"
    r"dubai|abu dhabi|uae|saudi|riyadh|qatar|doha|"
    # country names only — city names like Cairo/Jordan collide with US towns
    r"egypt|\boman\b|muscat|kuwait|bahrain|amman|lithuania|vilnius|"
    r"canada|toronto|vancouver|ontario|australia|sydney|melbourne|singapore|philippines|"
    r"malaysia|hyderabad|bangalore|bengaluru|chennai|mumbai|pune|noida|gurgaon|delhi|"
    r"ireland|germany|poland|romania|mexico|\bmx\b|brazil|colombia|"
    r"argentina|buenos aires|chile|peru|santiago|"
    # --- Indian metros beyond the first batch. Offshore delivery centers are
    # the single biggest source of out-of-scope postings; "Kolkata" (Accenture)
    # slipped through on 2026-08-06. gurugram = modern spelling of gurgaon.
    r"kolkata|calcutta|gurugram|ahmedabad|jaipur|coimbatore|kochi|cochin|"
    r"trivandrum|thiruvananthapuram|mysuru|mysore|nagpur|indore|chandigarh|"
    r"vadodara|surat|bhubaneswar|visakhapatnam|madurai|lucknow|thane|"
    r"navi mumbai|\bgoa\b|karnataka|maharashtra|telangana|tamil nadu|kerala|"
    r"gujarat|haryana|uttar pradesh|west bengal|andhra pradesh|"
    # --- other common offshore/delivery hubs, country names first
    r"sri lanka|colombo|bangladesh|dhaka|nepal|kathmandu|pakistan|karachi|lahore|"
    r"vietnam|viet nam|hanoi|ho chi minh|indonesia|jakarta|thailand|bangkok|"
    r"kuala lumpur|manila|quezon city|makati|taguig|cebu|"
    r"shanghai|beijing|shenzhen|guangzhou|hong kong|taiwan|taipei|"
    r"japan|tokyo|osaka|south korea|seoul|"
    r"turkey|turkiye|istanbul|ankara|ukraine|kyiv|kiev|lviv|belarus|minsk|"
    r"bulgaria|serbia|croatia|zagreb|czech|czechia|slovakia|bratislava|"
    r"hungary|budapest|bucharest|estonia|tallinn|latvia|riga|slovenia|"
    r"portugal|porto|spain|barcelona|netherlands|belgium|"
    r"switzerland|zurich|austria|sweden|norway|denmark|finland|"
    r"morocco|casablanca|tunisia|nigeria|kenya|nairobi|ghana|"
    r"south africa|johannesburg|cape town|durban|pretoria|"
    r"new zealand|auckland|israel|tel aviv|jerusalem|"
    r"costa rica|guatemala|ecuador|uruguay|paraguay|bolivia|"
    r"venezuela|dominican republic|honduras|el salvador|nicaragua|"
    r"puerto vallarta|guadalajara|monterrey|tijuana|queretaro|"
    r"bogota|medellin|lima peru|sao paulo|rio de janeiro|"
    r"emea|apac|latam)\b", re.I)

# Cities that name both a foreign metro and a US town (Cairo IL, Athens GA,
# Moscow ID...). Treated as non-US ONLY when the location carries no US
# marker. Added 2026-07-30 after PwC's "Cairo - ETIC" postings (their Egypt
# delivery center) slipped onto the board.
# london/dublin live here rather than in NON_US because London OH and
# Dublin OH are real US job locations; their country names still match above.
# china/greece/italy/panama city are countries-or-US-towns (China TX, Greece NY
# pop 96k, Italy TX, Panama City FL) so they must never be unconditional.
AMBIGUOUS_CITY = re.compile(r"\b(cairo|athens|moscow|lima|dublin|london|"
                            r"manchester|birmingham|naples|odessa|versailles|"
                            r"china|greece|italy|panama city|belgrade|warsaw|"
                            r"aberdeen|wellington|glasgow|bristol|oxford|"
                            r"amsterdam|vienna|berlin|geneva|paris|rome|milan|"
                            r"florence|hamburg|lisbon|madrid|prague|toledo|"
                            r"stockholm|belfast|sofia|st petersburg)\b",
                            re.I)
US_MARKER = re.compile(
    r"\b(united states|u\.?s\.?a?|remote|"
    r"al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|"
    r"ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|"
    r"wa|wv|wi|wy|dc|"
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|"
    r"delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
    r"kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
    r"mississippi|missouri|montana|nebraska|nevada|ohio|oklahoma|oregon|"
    r"pennsylvania|tennessee|texas|utah|vermont|virginia|washington|"
    r"wisconsin|wyoming)\b", re.I)

COMP_RE = re.compile(
    r"(?:salary|pay|compensation|range|rate)[^.\n]{0,80}?"
    r"(\$[\d,]+(?:\.\d+)?(?:\s*[-–to]+\s*\$?[\d,]+(?:\.\d+)?)?"
    r"(?:\s*(?:/|per\s*)?(?:year|yr|hour|hr|annum|annually|hourly))?"
    r"[^.\n]{0,120}?(?:bonus|equity)?[^.\n]{0,40})", re.I)
DOLLAR_RANGE_RE = re.compile(
    r"\$[\d,]{4,}(?:\.\d+)?\s*(?:[-–]|to)\s*\$?[\d,]{4,}(?:\.\d+)?"
    r"(?:\s*(?:/|per\s*)?(?:year|yr|hour|hr|annum|annually|hourly))?", re.I)
SALARY_NUM_RE = re.compile(r"\$?([\d,]+(?:\.\d+)?)\s*([kK])?")


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
    if not location:
        return False
    if NON_US.search(location):
        return True
    # ambiguous city + no US state/country marker anywhere => foreign
    return bool(AMBIGUOUS_CITY.search(location)
                and not US_MARKER.search(location))


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
    nums = []
    for num, suffix in SALARY_NUM_RE.findall(comp):
        raw = num.replace(",", "")
        if not raw.replace(".", "").isdigit():
            continue
        n = float(raw)
        if suffix:      # "$141K" means 141,000 — not 141
            n *= 1000
        elif n < 20:    # ignore stray small numbers
            continue
        nums.append(n)
    if not nums:
        return -1.0
    v = max(nums)
    if v < 1000:  # stated hourly rate; annualize for ordering only
        v *= 2080
    return v


def classify_role(title, description, roles):
    """Which KIND of job this is — systems / field / controls / unclear.

    A derived tag for filtering only (like the metro sort bucket), never a
    displayed claim about the posting; hard rule #1 is unaffected. Title hits
    outweigh body hits because boilerplate mentions ('we use Primavera
    Unifier') are exactly the false signal this exists to defeat. Anything
    ambiguous stays "unclear" rather than being guessed into a bucket, so a
    hide-filter can never silently drop a job on a weak signal.
    """
    t = (title or "").casefold()
    b = (description or "").casefold()
    tw = roles.get("title_weight", 6)
    scores = {}
    for kind, sig in (roles.get("kinds") or {}).items():
        s = sum(tw for term in (sig.get("title") or []) if term.casefold() in t)
        s += sum(1 for term in (sig.get("body") or []) if term.casefold() in b)
        scores[kind] = s
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    top = scores[best]
    if top < roles.get("min_score", 3):
        return "unclear"
    if sorted(scores.values())[-2:].count(top) > 1:   # tied leaders
        return "unclear"
    return best


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
