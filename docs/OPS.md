# Operations runbook

Internal ops notes for the defi4refi pipeline. Public-facing info lives in
the [README](../README.md).

## Current data

| Metric | Count |
|---|---|
| raw_leads | 292,752 rows / 37+ sources (incl. 1,117 `artizen-s7` projects) |
| orgs (entity-resolved) | 59,911 |
| contacts | 39,320 |
| funding_events | 37,360 |
| outreach_queue | 975 contact-ready (score>=35, verified contact, not contacted) |
| signals | 483 fresh triggers (karma/giveth/hypercerts/coingecko diffs) |
| llm_scores | 287 orgs scored |

## Tables

`raw_leads` · `orgs` · `lead_org_map` · `funding_events` · `contacts` ·
`org_github` · `signals` · `llm_scores` · `outreach_log` · `suppression` ·
`drafts` · `replies` · `org_outcomes` · `suppression_auto` ·
`draft_variant_log` · views: `v_scored`, `outreach_queue`, `channel_perf`
(live view over outreach_log+replies)

Learning-schema tables self-provision on any `outreach_agent.py` run — no
separate migration step.

## VPS layout (primary)

The pipeline is VPS-native (openhands-vps, `147.79.71.192`, repo at
`/root/defi4refi`). Hermes on that box owns messaging + intake builds.

- **ClickHouse**: docker `defi4refi-ch`, loopback-only `:8123`,
  `--restart unless-stopped`, volume `defi4refi-ch-data`.
- **LLM**: `scripts/.env` sets `LLM_PROVIDER=openai`,
  `LLM_URL=http://127.0.0.1:8081/v1`, `LLM_MODEL=auto` — freelm-gateway,
  the same provider Hermes uses (not laptop-dependent).
- **Systemd (system units on VPS)**: `defi4refi-outreach.timer` (6h cycle),
  `defi4refi-inbound.service` (:8899 replies webhook).
- **Hermes**: poll-based intake via `hermes cron` job `defi4refi-intake`
  every 2h (scans `[APPLY]` issues via `gh` — no public ingress needed);
  webhook `github-apply` exists for when `hooks.terex.dev` DNS lands;
  `defi4refi-digest` daily; `defi4refi-governor` weekly.
- **Builds — GitHub-native, no templates**: each application issue produces
  a fresh `defi4refi/<project>` repo composed from the applicant's wants.
  Hermes vendors individual modules from `oss-catalog.yaml` (upstream URLs,
  fetched per-build — nothing pre-cloned on the VPS), authors the glue in a
  transient workspace, pushes, and the repo's own GitHub Action
  (`tools/ci/verify-build.yml` → `.github/workflows/verify-build.yml`) runs
  `forge build/test` + license + <5% custom-code gates. rooted-finance is a
  module library, never a template.

## Laptop (read replica / dev)

- ClickHouse `defi4refi-ch` stays as a read replica; `ui/server.py` takes
  `CH_URL` env (e.g. `CH_URL=http://100.104.37.87:8123` via SSH tunnel:
  `ssh -L 8123:127.0.0.1:8123 root@147.79.71.192`).

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
- ReliefWeb (needs approved appname), Toucan subgraph (free Graph key),
  Farcaster (Neynar key)
- VC portfolio spiders need Firecrawl (JS pages)

## Output

`data/top300.csv` — ranked orgs w/ funding$, recency, LLM regen/need +
reason, contacts, why-breakdown.
