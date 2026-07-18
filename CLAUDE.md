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

## The artifact (live mobile/claude.ai view)

- URL (stable, redeploys in place): https://claude.ai/code/artifact/608cd631-fd87-4549-a241-6558b72d13c3
- Source of truth: `artifact/unifier-job-watch.html` in THIS repo. Edit it here,
  then publish with the Artifact tool passing `url:` = the URL above (any session
  from the owner's account can do this; without `url:` you'd mint a new address —
  never do that). Favicon stays 📡.
- Data contract: the page reads ONLY `data/feed.json` (keep it under ~100KB;
  descriptions live in `data/descs/{id}.txt`, lazy-loaded per card) through the
  user's claude.ai GitHub connector (`server: "GitHub"`, tool
  `get_file_contents`, args `{owner, repo, path}`).
- HARD-WON WIRE FORMAT (do not regress): in the artifact runtime,
  get_file_contents returns content blocks
  `[{type:"text", text:"successfully downloaded ... (SHA: ...)"}, {type:"resource", resource:{uri, mimeType, text:<FILE CONTENT>}}]`
  and `payload` is just the useless message string. The page's `fileStrings()`
  reads resource blocks + strips the SHA prefix — keep that parser, and keep the
  raw-event debug dump (20s timeout box) that diagnosed it.
- Keep the page's sort/badges in sync with `scraper/site_gen.py` when either changes.

## Current state (update this section when you change it) — as of 2026-07-17

- Baseline run done: 0 structured listings, 3 triage entries (Meta, DRMcNatty = likely a
  real Unifier posting, Project Partners = known marketing-copy false alarm → mark ignored).
- 13 of ~27 roster companies enabled; disabled ones have inline notes in companies.yaml.
- Open work: extract Meta + DRMcNatty postings from triage; fix Oracle ORC finder syntax;
  find correct Workday cxs tenants for WSP / Burns & McDonnell / Mass General Brigham;
  MTA blocked by 403 bot wall; aggregator API keys not yet added (discovery layer dormant).
- Gotcha: `generic_page` sources check RAW html, not extracted text — job data on JS-heavy
  sites lives in embedded script JSON.
