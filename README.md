# defi4refi lead pipeline

ClickHouse-backed lead engine: discover → resolve → enrich → score → queue → outreach.

## Current state

| Metric | Count |
|---|---|
| raw_leads | 92,816 rows / 37 sources |
| orgs (entity-resolved) | 38,596 (571+ cross-source clusters) |
| orgs with funding $ | 12,108 (USASpending, OP cycles, Filecoin ProPGF, 990s, Giveth, World Bank, OC, hypercert sales, self-reported) |
| contacts | 2,723 (898 MX-verified emails, 1,135 twitter, 232 github) |
| outreach_queue | 344 contact-ready (score≥35, verified contact, not contacted) |
| signals | 483 fresh triggers (karma/giveth/hypercerts/coingecko diffs) |
| llm_scores | ~273 orgs scored via laptop Ollama |

## Tables

`raw_leads` · `orgs` · `lead_org_map` · `funding_events` · `contacts` · `org_github` · `signals` · `llm_scores` · `outreach_log` · `suppression` · views: `v_scored`, `outreach_queue`

## Scripts (`scripts/`)

| Script | Role |
|---|---|
| `build_leads.py` | original multi-source fetch |
| `fetch_karma.py` | Karma GAP paginator |
| `load_extra_sources.py` | github topics, celo, dexscreener, ungc |
| `load_registries.py` | ProPublica, WorldBank, OpenCollective, grants.gov (+ReliefWeb gated) |
| `load_bulk.py` | ACNC CSV, Brønnøysund API |
| `load_scale.py` | **USAspending** env agencies, OC-all, Giveth-all, ProPublica-broad |
| `load_portfolios.py` | VC portfolio scrapes (JS-gated → needs Firecrawl) |
| `resolve_entities.py` | union-find entity resolution → orgs/map |
| `funding_amounts.py` | promote real $ to funding_events |
| `enrich.py` | website email scrape + github API |
| `verify_github.py` | MX email verify + github org HTML scrape |
| `llm_score.py` | Ollama relevance pass → llm_scores |
| `diff_signals.py` | multi-source weekly diff → signals |
| `governor.py` | queue-depth check + escalation ladder |
| `score.sql` / `outreach_queue.sql` | scoring + queue views |

## Cron

```cron
0 4 * * 1 cd ~/CascadeProjects/defi4refi && python3 scripts/diff_signals.py && python3 scripts/governor.py
```

## Remaining bulk sources (path to 100k funded)

Blocked/gated today, need retry or manual download:
- UK Charity Commission register bulk (site 502'd — monthly file)
- Canada CRA T3010, CORDIS bulk, 360Giving datastore, EU FTS, India NGO Darpan
- ReliefWeb (needs approved appname), Toucan subgraph (free Graph key), Farcaster (Neynar key)
- VC portfolio spiders need Firecrawl (JS pages)

## Output

`data/top300.csv` — ranked orgs w/ funding$, recency, LLM regen/need + reason, contacts, why-breakdown.
