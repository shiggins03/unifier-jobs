# Unifier job watch

Personal aggregator for Oracle Primavera **Unifier** job postings (secondary:
P6 / OPC / PIF / OIC with Primavera context). Direct employer listings are the
product; job boards are used for discovery only.

**Dashboard:** GitHub Pages serves `docs/index.html` (regenerated daily).

## Hard rules

- **No guessed data, ever.** Every displayed field (salary/bonus/equity, posted
  date, location, description) is verbatim from the source or shows "Not listed".
  Sorting may *classify* stated data (Brooklyn → NYC bucket); display never changes.
- **US + remote-US scope only.**
- **Direct listings first.** Board copies of roster-company jobs are dropped;
  unknown-employer board finds go to the triage queue and a collapsed section.
- **Spam is hard-filtered** to `data/quarantine.jsonl` (see `config/blocklist.yaml`),
  never shown.
- **LinkedIn/Indeed are never scraped.** Their content arrives indirectly via
  the discovery APIs.

## How it works

Daily GitHub Actions run (`.github/workflows/daily.yml`):

1. Fetch every `enabled: true` company in `config/companies.yaml` (Workday /
   Oracle ORC / Greenhouse JSON APIs; `generic_page` monitors do a keyword
   presence check and route hits to the triage queue).
2. Fetch discovery APIs (JSearch, Adzuna, Jooble) — each silently skipped if
   its key isn't configured.
3. Filter (keyword tiers, US scope, 90-day cutoff on board finds, blocklist),
   dedup (direct wins), resolve board hits against the roster.
4. Expire listings that vanish from their source (marked "no longer listed",
   never deleted). Flag stale posts "long-posted".
5. Health-check every source; warnings appear on the dashboard banner.
6. Write `data/jobs.jsonl`, regenerate `docs/index.html`, commit.

Sort order: keyword tier → company tier (A/B/C in `companies.yaml`) → stated
comp (unlisted sorts below; parsed for ordering only) → metro rank
(`config/cities.yaml`: NYC, LA, SF, Miami, Boston, remote, other US).

## Triage queue (`data/needs_triage.json`)

Entries are companies/links needing judgment: fingerprint an ATS endpoint,
extract a posting from a careers page, or classify an unknown employer. The
triage agent (or a human) resolves each entry and proposes roster changes via
PR. **Convention: never delete entries — add `"status": "handled"` or
`"status": "ignored"` so the entry isn't re-queued next run.**

Known first-run false alarm: Project Partners' careers page mentions Unifier in
marketing copy — mark ignored.

## Setup (one-time)

1. Create free API keys: [JSearch on RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch),
   [Adzuna](https://developer.adzuna.com/), [Jooble](https://jooble.org/api/about).
2. Repo → Settings → Secrets and variables → Actions → add
   `JSEARCH_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`.
   (Pipeline works without them — direct monitors only.)
3. Repo → Settings → Pages → deploy from branch `main`, folder `/docs`.

## Local run

```
pip install -r requirements.txt
python -m scraper.main
```

First run with an empty `data/jobs.jsonl` is a baseline: everything found is
recorded but nothing is flagged "new".
