# defi4refi lead pipeline

ClickHouse-backed lead engine: discover → resolve → enrich → score → queue → outreach.

**Funnel**: X/Twitter + outreach channels →
[github.com/TerexitariusStomp](https://github.com/TerexitariusStomp) (the studio's
landing page) → **submit an idea** via the
[apply-for-build issue template](.github/ISSUE_TEMPLATE/apply-for-build.md)
(see [APPLY.md](APPLY.md)) or **join the community** at
[t.me/defi4refi](https://t.me/defi4refi).

## Current state

| Metric | Count |
|---|---|
| raw_leads | 292,752 rows / 37+ sources (incl. 1,117 `artizen-s7` projects) |
| orgs (entity-resolved) | 59,911 |
| contacts | 39,320 |
| funding_events | 37,360 |
| outreach_queue | 975 contact-ready (score≥35, verified contact, not contacted) |
| signals | 483 fresh triggers (karma/giveth/hypercerts/coingecko diffs) |
| llm_scores | 287 orgs scored via local Ollama |

## Tables

`raw_leads` · `orgs` · `lead_org_map` · `funding_events` · `contacts` · `org_github` · `signals` · `llm_scores` · `outreach_log` · `suppression` · `drafts` · `replies` · `org_outcomes` · `suppression_auto` · `draft_variant_log` · views: `v_scored`, `outreach_queue`, `channel_perf` (live view over outreach_log+replies)

Learning-schema tables self-provision on any `outreach_agent.py` run — no separate migration step.

## Ops

- **ClickHouse**: `docker start defi4refi-ch` (container `defi4refi-ch`,
  image `clickhouse/clickhouse-server:25.7`, host port 127.0.0.1:8123).
  Default user is open inside the container — port is loopback-only.
- **Ollama**: `systemctl --user status ollama` (serves `llama3.1-8b-tools-32k`).
- **Outreach cycle**: `defi4refi-outreach.timer` — `outreach_runner.py once`
  every 6h (draft → LLM-approve → send → triage → learn → report).
- **Inbound webhook**: `defi4refi-inbound.service` — replies endpoint on :8899.
- **Credentials**: copy `scripts/.env.example` → `scripts/.env` (gitignored).
  Unconfigured channels are skipped; pipeline still drafts + logs `would_send`.
- **Lead browser**: `python3 ui/server.py` → http://localhost:8471 (needs ClickHouse).

Restore from snapshot: see `data/snapshot/RESTORE.md` (POST inserts —
`--data-binary @-` with the query as a URL param; do NOT mix `--get` +
`--data-binary`, it silently drops the body).

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
