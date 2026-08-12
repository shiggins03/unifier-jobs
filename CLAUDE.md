# unifier-jobs

Aggregates job postings mentioning Oracle Primavera **Unifier**. A posting must
say "Unifier" — nothing else qualifies. The old tier-2 keywords (P6/OPC/PIF/OIC)
were removed 2026-08-07 by owner decision: "I don't want it if it doesn't
specifically call out unifier." Do not re-add them without asking; see the note
in `config/keywords.yaml` for how, and why it was dropped.
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
- Role filtering: `ui.roles` is show-only, `ui.hideroles` is exclude. **`hideroles`
  defaults to `["field"]`** — the owner is a systems person and asked for
  welding/superintendent postings to be weeded out; the chip toggles it, "Clear
  filters" releases it, and the count line always says how many are hidden, so
  nothing is dropped silently. Turning on a role's show-only chip releases its
  hide chip (and vice versa) so the two can't render an empty list. The static
  dashboard has no chips, so `site_gen.py` gives field roles their own collapsed
  section instead — keep the two surfaces equivalent.
- Applied-tracking lives ONLY in the artifact (localStorage key
  `ujw-applied-v1`, job id -> ISO tick date). Job ids hash
  company|title|location, so a tick survives daily re-fetches. It is
  per-browser, NOT synced across devices and NOT in the repo. Ticking updates
  the card in place rather than re-rendering, so an open description stays
  open — keep that if you touch the handler.

## US-only scope filter (`filters.is_non_us`)

Three layers: `NON_US` (unambiguous countries/metros — always foreign),
`AMBIGUOUS_CITY` (names shared with US towns — foreign ONLY when no US marker
is present), `US_MARKER` (states, abbreviations, "remote"). Both failure modes
are costly: a missed metro puts out-of-scope jobs on the board, an over-broad
pattern silently deletes real US jobs. **Never add a city to `NON_US` without
checking for a US namesake** — Greece NY (pop 96k), Panama City FL, Vienna VA,
Athens GA, Warsaw IN, Aberdeen SD all exist; those belong in `AMBIGUOUS_CITY`.
`\b` boundaries matter: `india` must not match "Indiana".
`python -m scraper.test_filters` asserts both directions — add a case for every
pattern you add. Scope is re-applied to the whole store each run, so tightening
the filter retroactively purges stored postings.

## Role classifier (`config/roles.yaml`)

The owner is a Unifier SYSTEMS person (admin/config/integration/development),
NOT a construction engineer or scheduler — but Bechtel's welding field
engineers and Turner & Townsend's schedulers match because Unifier/P6 appears
in their boilerplate. `classify_role()` tags each posting systems / controls /
field / unclear, surfaced as artifact filter chips and a muted card badge.
- DERIVED, not stated: it is a filter tag in the same category as the metro
  sort bucket. Hard rule #1 still holds — title/comp/location/description
  render verbatim, and both surfaces say so in the footer.
- Title hits outweigh body hits (title_weight), because boilerplate mentions
  are the exact false signal this defeats. Ambiguous => "unclear", never
  guessed into a bucket, so a hide-filter can't silently drop a real job.
- Highest-precision signal is `unifier` in the TITLE => systems. Without it
  Oracle's "Senior Principal Consultant-Oracle Primavera Unifier" and NYP's
  "Facilities Systems (Oracle Unifier)" both fell through to unclear.
- COUNTER-INTUITIVE, do not "fix" it: naming SIBLING PMIS platforms (Kahua,
  EcoSys, Procore, e-Builder, Aconex) in the body is a POSITIVE systems
  signal, not a false match. A posting only reaches this board by matching
  Unifier/P6 first, so a competitor list marks platform work. Added 2026-07-31
  for Deloitte's "Sr. Consultant – Capital Projects", a role the owner applied
  to IRL whose generic title left it "unclear"; its systems signal was
  body-only ("configuration and implementation of Project Management
  Information Systems (PMIS)"). Verified as the ONLY reclassification across
  all 83 active jobs. Construction postings do pick up these terms (Bechtel
  +aconex, STV/T&T +ecosys) but title_weight holds them in place — narrowest
  margin was STV "Senior Cost Engineering Specialist", ctl=7 vs sys=4.
- Tune the term lists in roles.yaml; no code change needed. ALWAYS diff the
  whole store old-config-vs-new before committing a term-list change — a
  broad term can silently migrate whole employers between kinds.

## Hand-copied comp (`config/comp_overrides.yaml`)

Meta renders its pay range client-side: it is in neither the job_details HTML
nor the schema.org JSON-LD (which has no `baseSalary`), so no server fetch can
ever see it. An override supplies that string, COPIED VERBATIM from the live
posting, keyed by URL substring. It fills an empty comp only — it can never
replace or contradict what a feed reported — and the card is badged "comp
copied by hand" on both surfaces so provenance is never ambiguous. Hard rule #1
is intact: the exception is to how the string is obtained, not to what may be
shown. Delete entries when postings close. Does not scale to every Meta job by
hand; the scalable fix would be rendering their pages with a headless browser,
which nobody has asked for yet.

## Adding a job from a direct link (`config/seed_jobs.yaml`)

The escape hatch for employers whose sites refuse automated clients (MTA,
Port Authority, NYPA, Burns & McDonnell, MARTA...). Paste the job URL plus
whatever fields can be copied VERBATIM from the posting; it renders as a
normal direct listing badged "manual". Hard rule #1 is unchanged — copy, never
paraphrase or reconstruct a title from the URL slug; omit what you can't copy
and it shows "Not listed". Give `tier:` explicitly when no description was
copied, since the keyword filter would otherwise see only the title. Seeds are
"seen" every run, so they never age out — delete the entry when it closes.

## JSearch free tier does NOT include search (verified 2026-07-30)

A live key on RapidAPI's free plan (X-RateLimit-Requests-Limit: 200) reaches
JSearch fine — /job-details, /estimated-salary, /company-job-salary all
return 200 — but /search and /search-filters answer 404 "Endpoint does not
exist". 27 path variants plus POST were swept: it is plan gating, not a
rename. The working endpoints are useless here (/estimated-salary would
violate hard rule #1 anyway). fetch_jsearch now treats that 404 as
"unavailable" instead of a failure so it stops raising daily health warnings.
NEXT CANDIDATE: Adzuna — direct API, not a marketplace with per-endpoint
gating, and its search endpoint is the core of the free developer tier.

## Key-free aggregators: searched, none viable (2026-07-30)

Hunted a zero-key, zero-human route for the Cloudflare-walled employers
(MTA et al). All dead — do not re-run without a new candidate:
- The Muse public API: `q` is not real full-text; "unifier" returns LPN /
  PCB Technician / Retail Merchandiser.
- governmentjobs.com/jobs?keyword=: stems to "unif" — hits are Unified
  Sports Coach / Reunification / Unified Family Court. No MTA (not NEOGOV).
- jobs.apta.com: reachable, but "unifier" occurrences == query-echo count,
  i.e. no real Unifier postings; also has an all-jobs fallback on no match.
- Careerjet (403 without affiliate id), careersingovernment (0),
  transitjobs (404), statejobs.ny.gov (404).
The coded JSearch/Adzuna/Jooble adapters remain the only automated route,
and each needs one free API key in repo secrets.

## Diagnosing endpoints (the probe workflow)

Claude-session sandboxes usually can't reach career sites (proxy policy), but
GitHub Actions can. `scraper/probe.py` + `.github/workflows/probe.yml`
(workflow_dispatch only): write probes into `main()`, push, dispatch, read the
Actions log, iterate. `run_adapter()` exercises a real adapter end-to-end
before trusting it in the daily run. Keep `main()` empty between
investigations.

## Current state (update this section when you change it) — as of 2026-08-07

- **Unifier-only board.** Tier 2 removed: `keywords.yaml` has no `tier2:` block,
  `keyword_tier()` treats it as optional, `main.run()` purges stored postings
  whose tier isn't live (keyed off the STORED tier, never re-derived — a
  tier-1 job whose description failed to fetch, or a manual seed that declared
  its tier, must survive). Dropped ~30 postings, mostly Turner & Townsend.
  Both surfaces lost their "Related keywords" section and the artifact its
  "Related (P6/OPC…)" chip; the artifact also filters the feed to `tier === 1`
  so a cached feed can't leak tier-2 into the board-finds/gone sections.
- Direct monitors still search "unifier" only. Widening them to also query
  "primavera" was tried and reverted the same day — it surfaced OPC/P6 roles
  that are now out of scope by definition.
- Added Moss (tier B, workday mosscm/Moss_Careers) — ENR top-65 GC building an
  in-house Oracle team. Note: under Unifier-only rules they currently have
  **zero** qualifying postings; kept on the roster because they are an active
  Oracle/Primavera shop likely to post one.

## Previous state — as of 2026-08-06

- Added Argano (tier B, oracle_orc CX_1 on fa-eyau-saasfaprod1) — Oracle
  consultancy that bought Oracle Primavera partner American Process Management
  in Apr 2026. Endpoint verified end-to-end 2026-08-06: their Oracle Cloud PPM
  Delivery Architect (US, posted 08-05) qualifies tier 1 (Unifier named under
  requirements as a plus); the Canadian twin is dropped by the US filter.
  Their ORC link is only exposed as the "Join our team" anchor on
  argano.com/careers — the careers page itself has no ATS markers.

## Previous state — as of 2026-07-30

- Tier meaning changed: company tier is now GENERAL-MARKET PRESTIGE/COMP
  (see companies.yaml header), and it leads the sort inside each keyword
  section — an elite employer's desc-mention outranks a boutique's
  Unifier-titled role, by owner preference.
- Tier-A expansion (probe rounds 11-13), all endpoint-verified: Amazon (new
  `amazon_jobs` adapter — public search.json, full-text, nonsense query
  returns 0 so no echo guard needed), Eli Lilly (phenom; CONFIRMED Unifier
  user, 3 US project-controls roles on first run), Johnson & Johnson
  (workday jj/JJ), Pfizer, NVIDIA, Intel, Micron, PwC. 28 of 43 enabled.
- Gotcha: Workday's fuzzy searchText makes NVIDIA/Intel/Pfizer return
  unrelated postings for "unifier" (NVIDIA matches "Unified Memory"). The
  keyword tier filter drops them — expected noise, not breakage.
- Rejected after verification (do not re-add without fixing first): EY
  (SF search works but description selector doesn't match their markup →
  would flood triage), Northwell findly mirror (echoes the query 15x for
  ANY input — blind), Turner Construction csod API (401, token required).
- ALWAYS run an echo/negative control before trusting a keyword search:
  query a nonsense string and confirm the result differs. Round 12 caught
  Northwell this way after round 11 looked like a hit.

## Previous state — as of 2026-07-20

- NYC-focused roster expansion (probe rounds 5-10): ADDED & VERIFIED —
  City of New York (cityjobs.nyc.gov, generic_page with a jid-href
  check_pattern because the search echoes queries), STV (Workday wd5/stv,
  found via stvinc.com link; a NYC "Project Solutions Lead" in first results),
  Hill International (Oracle ORC hcib/CX_1001 via hillintl.com links; new
  job_url_base config generalizes the ORC adapter), Amtrak (new
  successfactors adapter — CSB no-match searches fall back to ALL jobs, so
  results only count when they differ from a nonsense query; 3 NYC project
  controls jobs in first results).
- New-company dead ends documented inline in companies.yaml: Turner
  Construction (Cornerstone SPA), PANYNJ + NYPA (Workday hosts exist, site
  names undiscoverable), NJ Transit/DASNY/SCA (no scriptable endpoints found).
- MTA verdict is FINAL (see its note): Cloudflare on everything, no script
  route; aggregator discovery is the only path. Do not re-scrape.

## Previous state — as of 2026-07-18

- Broken-roster sweep done (probe rounds 1-4, see companies.yaml notes for
  per-company verdicts). Fixed: Oracle ORC (limit=25 truncated the one
  unifier-mentioning req of 27 — now 100, TotalJobsCount as inventory),
  Mass General Brigham (Workday tenant renamed partners → massgeneralbrigham,
  site MGBExternal), Turner & Townsend (new smartrecruiters adapter; their old
  careers domain now redirects to a marketing page). Accenture cxs is
  intermittently flaky, left enabled.
- Confirmed dead ends (disabled, reasons inline in companies.yaml): WSP,
  Burns & McDonnell, MTA, LA Metro, MARTA, Northwell, Petrofac (no US board),
  CDP (no careers page), Compass (no careers page). Most become reachable only
  via the discovery layer — aggregator API keys still not added (dormant).
- Open work: extract Meta + DRMcNatty postings from triage; add aggregator
  keys; Accenture custom-portal adapter if cxs flakiness worsens.
- Gotcha: `generic_page` sources check RAW html, not extracted text — job data on JS-heavy
  sites lives in embedded script JSON.
- Gotcha: Workday cxs searchText is fuzzy — JLL/MGB return ~20 unrelated
  postings for "unifier"; the tier filter drops them, expected noise.
