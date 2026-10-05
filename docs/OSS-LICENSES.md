# OSS Licenses — canonical inventory & reuse audit

Machine-readable version: [`oss-catalog.yaml`](../oss-catalog.yaml). Regenerate/extend
whenever a template is added or a vendored dep changes. Obligation checker:
`trivy fs --scanners license` or manual LICENSE read (licenses pinned below were
verified against each repo's LICENSE/COPYING/SPDX headers on 2026-10-05).

**Policy**: every component below is usable under the defi4refi policy — permissive,
copyleft (GPL/AGPL/LGPL/MPL), and source-available (BUSL/SSPL/BSL) are all allowed;
copyleft is fine. Obligations are recorded per component and MUST be preserved in
delivered repos (attribution, license text, NOTICE retention, share-alike source
publication — which is satisfied anyway since all deliverables ship as public repos).
No component is banned, but its license class is truthfully recorded so obligations
are never lost.

## Studio-owned templates (fork/adapt for client builds)

| Repo | License | Class | Reuse | Obligation |
|---|---|---|---|---|
| defi4refi/rooted-finance | AGPL-3.0 | copyleft | T1 contracts + T2 frontend master template | publish source, keep AGPL headers |
| defi4refi/abyayala | AGPL-3.0 | copyleft | T1 secondary contract patterns | publish source |
| Rooted monorepo (`~/Documents/Rooted`) | AGPL-3.0 | copyleft | T3 workers/lexicons/appreciation | publish source |
| postearn | AGPL-3.0 | copyleft | T3 posting/earning modules | publish source |
| village-os | MIT | permissive | T2 community/admin UI | keep copyright |
| regen-atlas | MIT | permissive | T2 atlas/map UI | keep copyright |
| localchimera | internal copyright | — | T3 ecash/Casper experiments | owned code, no external obligations |
| rooted-wallet-extension | none on disk | — | T3 wallet integrations | owned code; add license header on reuse |
| regen-bridge, comeunity, agritrace, bridgew2w3, widespread-logos, ReGenCivics.Earth, volunteer-ecovillage-locations | none on disk | — | project-specific assets | owned code; verify before reuse |

## Vendored solidity stack (rooted-finance/contracts/lib — 27 submodules)

| Package | License | Class | Obligation |
|---|---|---|---|
| OpenZeppelin contracts v4/v5/upgradeable (`openzeppelin`, `openzeppelin-v4`, `oz-v4.8.0`, `oz-v5.3.0`, `openzeppelin-contracts-upgradeable`) | MIT | permissive | keep copyright line |
| OpenZeppelin `uniswap-hooks` | MIT | permissive | keep copyright |
| `forge-std` | MIT OR Apache-2.0 | permissive | test-only, keep copyright |
| `prb-math` | MIT | permissive | keep copyright |
| Reserve `reserve-index-dtf`, `trusted-fillers`, `reserve-governor` | MIT | permissive | keep copyright |
| `gmx-contracts` | MIT | permissive | keep copyright |
| Uniswap `v4-hooks-public` | MIT | permissive | keep copyright |
| `olympus-v3` | AGPL-3.0 | copyleft | share-alike; publish derived source |
| `bond-protocol` | AGPL-3.0 | copyleft | share-alike |
| `dss` (MakerDAO) | AGPL-3.0-or-later | copyleft | share-alike |
| `createx` | AGPL-3.0 | copyleft | share-alike |
| `spark-psm` | AGPL-3.0 | copyleft | share-alike |
| `tokenized-strategy` (Yearn) | AGPL-3.0 | copyleft | share-alike |
| `v2-core` + `v2-periphery` (Uniswap v2) | GPL-3.0-or-later | copyleft | share-alike |
| `core` (Lido) | GPL-3.0 | copyleft | share-alike |
| `balancer-v2-monorepo` | GPL-3.0-only | copyleft | share-alike |
| `vault-v2` (Morpho) | GPL-2.0-or-later | copyleft | share-alike |
| `euler-price-oracle` | GPL-2.0-or-later | copyleft | share-alike |
| `pendle-core-v2-public` + `pendle-sy` | mixed AGPL-3.0 / GPL-3.0-or-later / BUSL-1.1 | copyleft+source-available | per-file SPDX headers govern; BUSL parts convert to GPL at change date |
| Uniswap `v4-core` (dep of v4 hooks) | BUSL-1.1 | source-available | field-of-use + change-date (GPL-2.0-or-later) noted; allowed per policy |

## Gap-filler catalog (evaluate → clone to `/root/defi4refi/templates/` on first use)

| Repo | License | Class | Use |
|---|---|---|---|
| allo-protocol/allo-v2 | AGPL-3.0 | copyleft | quadratic funding / grant allocation |
| juice-contracts-v4 (Juicebox) | MIT | permissive | treasury / fundraising |
| safe-global/safe-smart-account | LGPL-3.0 | copyleft | multisig — prefer pointing at deployed singletons |
| Hats-Protocol/hats-protocol | MIT | permissive | roles / delegation |
| hypercerts-org/hypercerts | Apache-2.0 | permissive | impact certificates |
| ethereum-attestation-service/eas-contracts | see repo | permissive | attestations — integrate, don't fork |
| sablier-labs/* | BUSL-1.1 / GPL | source-available | payment streaming |
| OpenZeppelin Governor | MIT | permissive | DAO governance |

## Ops infrastructure

| Component | License | Use |
|---|---|---|
| ClickHouse server (docker) | Apache-2.0 | lead DB |
| hermes-agent fork | MIT | messaging/build agent |
| Ollama, Foundry, nginx, caddy | MIT / Apache-2.0 | inference, builds, edge |
| g4f / freelm-gateway | mixed | inference fallback — flag if studio commercializes |

## Deliverable requirement

Every client build repo ships a regenerated `docs/OSS-LICENSES.md` (vendored
components + license + obligation) and `docs/CUSTOM-CODE-AUDIT.md`
(`tools/custom-code.sh` output). Missing license docs fail build review.
