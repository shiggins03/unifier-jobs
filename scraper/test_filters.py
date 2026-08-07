"""Scope-filter regression test. Run: python -m scraper.test_filters

The US-only scope is hard rule #4, and the failure modes are asymmetric and
both bad: a missed foreign metro puts out-of-scope jobs on the board, while an
over-broad pattern silently deletes real US jobs (many foreign city names are
also US towns — Greece NY, Panama City FL, Vienna VA, Athens GA...). Every
pattern added to NON_US / AMBIGUOUS_CITY should gain a case here.
"""
import sys

from .filters import is_non_us

MUST_DROP = [
    # India — the offshore delivery centers that prompted this (Accenture's
    # "Kolkata" posting slipped through on 2026-08-06).
    "Kolkata", "Bengaluru, Karnataka, India", "Gurugram", "Ahmedabad, Gujarat",
    "Chennai, Tamil Nadu", "Kochi", "Hyderabad, Telangana", "Pune, Maharashtra",
    "Noida, Uttar Pradesh", "Coimbatore", "Thiruvananthapuram",
    # other common offshore/global hubs
    "Manila, Philippines", "Cebu", "Ho Chi Minh City", "Jakarta", "Bangkok",
    "Kuala Lumpur", "Dhaka, Bangladesh", "Karachi", "Colombo",
    "Shanghai", "Hong Kong", "Tokyo, Japan", "Seoul", "Taipei",
    "Istanbul", "Kyiv", "Budapest, Hungary", "Bucharest", "Minsk",
    "Barcelona, Spain", "Zurich", "Porto", "Amsterdam, Netherlands",
    "Johannesburg", "Cape Town", "Casablanca", "Nairobi", "Tel Aviv",
    "Auckland, New Zealand", "Guadalajara", "Bogota", "Sao Paulo",
    "Toronto, Ontario", "Dubai", "Riyadh", "Doha, Qatar",
    # ambiguous names WITH a foreign country attached
    "Athens, Greece", "Rome, Italy", "Panama City, Panama", "Beijing, China",
    "Paris, France", "Vienna, Austria", "Belgrade, Serbia", "Warsaw, Poland",
    # region codes used as locations
    "EMEA", "APAC", "LATAM",
]

MUST_KEEP = [
    # plain US
    "New York, NY", "Seattle, WA", "US-WA-Seattle", "US Remote", "Remote",
    "Queens, New York, United States", "Fresno, California, United States",
    # "India" must not match inside "Indiana"
    "Indiana, United States", "Indianapolis, Indiana, US",
    "Indianapolis, Indiana, United States of America", "Indiana, Indiana County",
    # US towns that share a name with a foreign country/metro
    "Panama City, FL", "Greece, NY", "China Grove, NC", "Italy, TX",
    "Vienna, VA", "Paris, TX", "Rome, GA", "Athens, GA", "Warsaw, IN",
    "Aberdeen, SD", "Wellington, FL", "Toledo, OH", "Milan, TN",
    "Berlin, CT", "Hamburg, NY", "Bristol, TN", "Oxford, MS",
    "Amsterdam, NY", "Florence, SC", "St Petersburg, FL", "Glasgow, KY",
    "Cambridge, MA", "Naples, FL", "Odessa, TX", "Lima, OH", "Dublin, OH",
    "Moscow, ID", "Cairo, IL",
]


def main():
    wrongly_dropped = [s for s in MUST_KEEP if is_non_us(s)]
    wrongly_kept = [s for s in MUST_DROP if not is_non_us(s)]
    for s in wrongly_dropped:
        print(f"FAIL  US location dropped: {s!r}")
    for s in wrongly_kept:
        print(f"FAIL  foreign location kept: {s!r}")
    if wrongly_dropped or wrongly_kept:
        print(f"\n{len(wrongly_dropped) + len(wrongly_kept)} failure(s)")
        return 1
    print(f"ok — {len(MUST_DROP)} foreign dropped, {len(MUST_KEEP)} US kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
