# Custom-Code Audit — <5% policy

**Rule**: delivered builds must be ≥95% vendored/forked OSS; custom-authored code
<5% of counted LOC, measured by `tools/custom-code.sh` (exits 1 when over — gates
builds and CI).

## How "custom" is counted

- **Counted**: `*.sol *.vy *.ts *.tsx *.js *.jsx *.py *.rs *.go *.sh *.sql *.css *.html *.svelte` … tracked by git.
- **Vendored/generated** (counts toward denominator): `lib/`, `vendor/`, `upstream/`,
  `third_party/`, `node_modules/`, `.venv/`, `dist/`, `out/`, lockfiles, `*generated*`,
  `*.pb.*`, minified, license/NOTICE files.
- **Not counted**: docs, config (json/yaml/toml/ini), tests/fixtures, `data/`,
  `ddl/`, snapshots, media.
- **Fork-based builds**: custom = diff vs the upstream fork point
  (`git diff upstream..HEAD -- <code extensions>` | `tools/custom-code.sh` on the
  worktree). Vendored submodules never count as custom.

## Current studio-repo audit (2026-10-05)

| Repo | Counted LOC | Custom % | Status |
|---|---|---|---|
| defi4refi (pipeline) | 3,846 | 97.5% | **exception** — internal tool, see note 1 |
| rooted-finance | 84,473 | 90.2% | **exception** — authored product = the template itself, see note 2 |
| abyayala | 155,723 | 97.8% | **exception** — authored product |
| regen-bridge | 50,207 | 5.3% | marginal overage — audit boundary: much is `data/`—like sol config; recheck excluding fixture-like paths |
| village-os | 407,061 | 60.1% | **exception** — authored product; vendored mass undercounted (pnpm deps not vendored) |
| regen-atlas | 23,724 | 98.4% | **exception** — authored product |

### Why studio products are flagged exceptions, not violations

The <5% cap exists so **client deliverables are assembled, not written** — leverage,
auditability, and speed come from vendoring battle-tested code. Studio-owned
products (the pipeline, rooted-finance, abyayala) *are* the reusable mass other
builds vendor from; they can't vendor themselves. They are audited for honesty and
carry reduction directions below, but they are not retrofit targets.

**Reduction notes**:
1. `defi4refi` pipeline — thin glue already (loaders/scorers are inherently bespoke);
   the custom `ui/server.py` + `ui/index.html` (~185 LOC) is a candidate to swap for
   an OSS ClickHouse dashboard (Metabase/Rill/Grafana-clickhouse). New pipeline
   features must prefer OSS libs over new scripts.
2. `rooted-finance` — the T1 template; its `src/` IS the product. Client forks of it
   are measured on their delta vs upstream, which must be <5%.
3. Per-deliverable enforcement is what actually matters — see below.

## Enforcement

- **Client builds (Hermes webhook → T1)**: the build brief requires vendoring from
  `oss-catalog.yaml` first; `tools/custom-code.sh` is run on the delivered repo and
  the output committed to `docs/CUSTOM-CODE-AUDIT.md`. Over 5% → build fails review
  unless an exception is documented in that file.
- **New studio code**: run `tools/custom-code.sh .` before merging; over 5% needs a
  documented exception here.
- **Exceptions** are recorded in this file (or the delivered repo's audit) with a
  one-line justification — never silently skipped.

## Per-build check (Hermes runs this)

```bash
tools/custom-code.sh /path/to/delivered-repo          # human-readable
tools/custom-code.sh /path/to/delivered-repo --json   # for the build report
# fork-based build: measure the delta vs upstream instead
git -C /path/to/repo diff --stat <upstream-tag>..HEAD -- '*.sol' '*.ts' '*.py'
```
