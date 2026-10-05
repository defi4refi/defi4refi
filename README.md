# defi4refi

**Free, open-source protocol engineering for ReFi and public-goods teams.**

Regenerative-finance projects have world-class vision and no engineering
budget. defi4refi is a public-goods development studio: supporters fund
the studio, and the studio designs and ships protocol codebases **free**
to selected teams.

## Want something built?

1. **[Submit your idea](https://github.com/defi4refi/defi4refi/issues/new?template=apply-for-build.md)**
   — open an application issue and tell us what you want built.
2. **[Join the community](https://t.me/defi4refi)** — discuss, ask
   questions, follow deliveries.

That's it. Applications are reviewed on a rolling basis.

## What we build

| Tier | Deliverable | Effort |
|---|---|---|
| T0 | Design sprint — tokenomics, architecture, threat model, roadmap | ~1 week |
| T1 | Protocol codebase — token, staking, bonds, treasury, governance | ~2–4 weeks |
| T2 | dApp frontend — staking/bonds/dashboard with a wallet stack | ~1–2 weeks |
| T3 | Adjacent modules — coordination, identity, DePIN, cross-chain | scoped |

## How a build works

Every project is built **for you, from your requirements** — there are no
templates.

1. You file an application issue describing what you want.
2. We triage it and create a fresh repository under the
   `defi4refi` org for your project.
3. The codebase is composed from production-proven open-source modules —
   OpenZeppelin, Olympus V3, Uniswap, Bond Protocol, and the contracts
   powering [rooted-finance](https://github.com/defi4refi/rooted-finance),
   [abyayala](https://github.com/defi4refi/abyayala), and
   [regen-bridge](https://github.com/defi4refi/regen-bridge) — glued with
   a thin layer of project-specific code (target: under 5%).
4. GitHub Actions on your repo builds, tests, and checks the license and
   custom-code gates on every push.
5. You get the repo URL on your issue. Audit-ready, not audited — your
   team deploys and operates the contracts under your own keys. Testnet
   only until your own audit and deployment.

## The open-source policy

- Everything we deliver is open source.
- We reuse commercially-usable OSS aggressively — permissive, copyleft,
  and source-available licenses are all fine. `oss-catalog.yaml` is the
  build menu: every candidate module with its license, obligations, and
  intended use. See `docs/OSS-LICENSES.md`.
- Custom code stays under 5% of a delivered codebase — measured in CI.
  See `docs/CUSTOM-CODE-AUDIT.md`.

## How it's funded

Donations go to the studio — donors receive no services (patronage of a
public good, not a service sale). Channels: Giveth, Octant, Gitcoin
rounds, direct crypto, and hypercerts minted on each delivered
engagement.

## What's in this repo

This repository also hosts the studio's outreach engine: a
ClickHouse-backed pipeline that finds ReFi/public-goods teams who might
need engineering help (292k+ leads from 37+ grant registries, funding
platforms, and ecosystem sources), scores them, and drafts outreach.
Internals are documented in `docs/OPS.md` — you don't need any of it to
apply for a build.
