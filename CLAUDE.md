# unifier-jobs

Aggregates job postings mentioning Oracle Primavera **Unifier** (secondary: P6/OPC/PIF/OIC,
only when Primavera/Oracle/project-controls context appears in the same posting).
Runs daily at 11:00 UTC via GitHub Actions; publishes a static dashboard to GitHub Pages
(https://shiggins03.github.io/unifier-jobs/). Owner: shiggins03 (solo project).

## Hard rules — never break these

1. **Never guess any displayed field.** Salary/comp, posted date, location, remote status,
   description: shown verbatim from the source or "Not listed". No estimates, no paraphrasing,
   no inferred dates. Sorting may classify stated data (e.g. Brooklyn → NYC bucket), but the
   displayed value stays verbatim.
2. **Free tier only.** Never add a paid API or service, even as an optional fallback,
   without the owner's explicit consent in that conversation.
3. **No LinkedIn/Indeed in the automated loop** — anti-bot walls and account-ban risk.
   Their content arrives indirectly via aggregator APIs.
4. **Direct listings are the product.** Aggregator APIs (JSearch/Adzuna/Jooble) are
   discovery only: resolve each hit to the employer's own ATS posting, add that employer to
   the roster, discard the board copy. Bulk staffing-firm spam goes to quarantine, not the
   dashboard. Scope: US + remote-US only.
5. **Triage agent output is config-only, via PR** — it proposes roster/config changes for
   review; it never writes job data directly.

## Layout

- `scraper/` — deterministic fetch/parse/dedup/publish (Python, stdlib+requests+yaml only)
- `config/companies.yaml` — monitor roster; per-source quirks are commented inline there
- `data/jobs.jsonl` — job store; `needs_triage.json` — agent queue (entries are never
  deleted; set status handled/ignored); `health.json` — per-source run counts
- `docs/index.html` — generated dashboard (do not hand-edit; edit `scraper/site_gen.py`)

## Current state (update this section when you change it) — as of 2026-07-17

- Baseline run done: 0 structured listings, 3 triage entries (Meta, DRMcNatty = likely a
  real Unifier posting, Project Partners = known marketing-copy false alarm → mark ignored).
- 13 of ~27 roster companies enabled; disabled ones have inline notes in companies.yaml.
- Open work: extract Meta + DRMcNatty postings from triage; fix Oracle ORC finder syntax;
  find correct Workday cxs tenants for WSP / Burns & McDonnell / Mass General Brigham;
  MTA blocked by 403 bot wall; aggregator API keys not yet added (discovery layer dormant).
- Gotcha: `generic_page` sources check RAW html, not extracted text — job data on JS-heavy
  sites lives in embedded script JSON.
