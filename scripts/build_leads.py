#!/usr/bin/env python3
"""Compile defi4refi leads database from Artizen dump, CoinGecko category, Giveth API, curated lists."""
import json, re, csv, time, urllib.request, urllib.parse

OUT = "/home/terex/CascadeProjects/defi4refi/data/leads.csv"
leads = []

def add(name, source, category="", raised="", website="", chain="", notes="", priority=""):
    leads.append({"name": name.strip(), "source": source, "category": category,
                  "raised_or_mcap_usd": str(raised), "website": website, "chain": chain,
                  "notes": notes.strip(), "priority": priority})

# ---------- 1. Artizen S7 dump ----------
art = open("/tmp/devin-overflows-1000/6df15c23/content.txt").read()
# Rows look like:  **[Name][N]**  │$73,868│...│$576,942│  with description on following lines
lines = art.splitlines()
# join wrapped project-name rows: a line starting "**[" whose "][N]**" closer is on a following line
merged = []
buf = ""
for ln in lines:
    if ln.startswith("**["):
        if buf:
            merged.append(buf)
        buf = ln
        if re.search(r"\]\[\d+\]\*\*", ln):
            merged.append(buf); buf = ""
    elif buf:
        buf += " " + ln.strip()
        if re.search(r"\]\[\d+\]\*\*", ln):
            merged.append(buf); buf = ""
    else:
        merged.append(ln)
if buf:
    merged.append(buf)
lines = merged
i = 0
proj_re = re.compile(r"^\*\*\[(.+?)\]\[\d+\]\*\*\s*(.*)$")
num_re = re.compile(r"\$[\d,.]+")
while i < len(lines):
    m = proj_re.match(lines[i])
    if m:
        name, rest = m.group(1), m.group(2)
        # block = name row + wrapped description lines (numbers are also split across them by │)
        block = [rest]
        desc_parts = []
        j = i + 1
        while j < len(lines) and j < i + 6 and not proj_re.match(lines[j]) and not lines[j].startswith("──"):
            block.append(lines[j])
            txt = re.split(r"[│|]", lines[j])[0].strip()
            if txt:
                desc_parts.append(txt)
            j += 1
        desc = " ".join(desc_parts)[:300]
        # table is sorted by raised desc — use rank as the funding signal (amounts
        # wrap mid-number across columns, too fragile to parse exactly)
        artizen_rank = sum(1 for l in leads if l["source"] == "artizen-s7") + 1
        add(name, "artizen-s7", category="grant-funded project",
            raised="", website="https://artizen.fyi/projects",
            notes=desc, priority=f"artizen-rank-{artizen_rank}")
        i = j
    else:
        i += 1

# ---------- 2. CoinGecko eco-friendly category ----------
cg = open("/tmp/cg_eco.json").read()
try:
    for c in json.loads(cg, strict=False):
        add(c["name"], "coingecko-eco", category="impact token",
            raised=c.get("market_cap") or "", website="https://www.coingecko.com/en/coins/" + c["id"],
            notes=f"symbol {c['symbol'].upper()}; mcap rank {c.get('market_cap_rank')}")
except Exception as e:
    print("coingecko parse:", e)

# ---------- 3. Giveth API — paginate sorted by donations ----------
def gql(query):
    req = urllib.request.Request(
        "https://mainnet.serve.giveth.io/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "authVersion": "2"})
    return json.load(urllib.request.urlopen(req, timeout=30))

TECH_KW = re.compile(r"dao|defi|protocol|token|chain|web3|open.?source|dapp|govern|coord|infra|dev|tech|data|network|platform|fund|financ|regen|refi|climate|environment|forest|energy|carbon|solar|water|ocean|land|eco|green|sustain|bio|agro|farm|reforest", re.I)
for skip in range(0, 400, 50):
    try:
        r = gql('{ allProjects(limit:50, skip:%d, sortingBy:MostFunded) { projects { title slug totalDonations verified descriptionSummary categories { name } } } }' % skip)
        for p in r["data"]["allProjects"]["projects"]:
            cats = ",".join(c["name"] for c in (p.get("categories") or []))
            text = (p["title"] or "") + " " + (p.get("descriptionSummary") or "") + " " + cats
            if TECH_KW.search(text):
                add(p["title"], "giveth", category="verified nonprofit/project",
                    raised=round(p.get("totalDonations") or 0),
                    website="https://giveth.io/project/" + p["slug"],
                    notes=(p.get("descriptionSummary") or "")[:200] + (" [cats: " + cats + "]" if cats else ""))
    except Exception as e:
        print("giveth skip", skip, ":", e)
        break

# ---------- 3b. Karma GAP (grant-funded projects, onchain attestations) ----------
import os
KARMA = "/tmp/karma_projects.jsonl"
if os.path.exists(KARMA):
    for line in open(KARMA):
        try:
            p = json.loads(line)
        except Exception:
            continue
        det = (p.get("details") or {}).get("data") or {}
        title = det.get("title") or (p.get("details") or {}).get("slug") or "?"
        links = {l.get("type"): l.get("url") for l in (det.get("links") or []) if isinstance(l, dict)}
        gh = (p.get("external") or {}).get("github") or []
        n_grants = len(p.get("grants") or [])
        raised = det.get("raisedMoney") or ""
        website = links.get("website") or links.get("orgWebsite") or ""
        notes = (det.get("description") or det.get("missionSummary") or "")[:200]
        if n_grants:
            notes = f"[{n_grants} grant(s)] " + notes
        if links.get("twitter"):
            notes += f" tw:{links['twitter']}"
        if gh:
            notes += f" gh:{gh[0]}"
        add(title, "karma-gap", category="grant-funded project (multi-program)",
            raised=raised, website=website, notes=notes)
else:
    print("karma jsonl not ready — skipping")

# ---------- 3c. GitHub topic search ----------
for topic in ["refi", "regenerative-finance", "regen", "carbon-credits", "hypercerts",
              "public-goods", "toucan", "klimadao", "quadratic-funding"]:
    try:
        req = urllib.request.Request(
            f"https://api.github.com/search/repositories?q=topic:{topic}&per_page=30&sort=stars",
            headers={"User-Agent": "defi4refi-leads"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        for r in d.get("items", []):
            add(r["full_name"], "github-topic-" + topic, category="oss repo",
                website=r["html_url"], raised=r.get("stargazers_count") or 0,
                notes=(r.get("description") or "")[:200] + f" [{r.get('language') or ''}]")
        time.sleep(1)
    except Exception as e:
        print("github", topic, ":", e)

# ---------- 3d. Regen Network ecocredit projects (Cosmos LCD) ----------
try:
    key = ""
    for _ in range(10):
        url = "https://lcd-regen.keplr.app/regen/ecocredit/v1/projects?pagination.limit=100"
        if key:
            url += "&pagination.key=" + urllib.parse.quote(key)
        req = urllib.request.Request(url, headers={"User-Agent": "defi4refi-leads"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        for pr in d.get("projects", []):
            add(f"{pr.get('class_id','?')}/{pr.get('id','?')}", "regen-ecocredit",
                category="ecocredit project", chain="Regen",
                notes=f"jurisdiction {pr.get('jurisdiction','?')} admin {pr.get('admin','')[:20]}… meta {pr.get('metadata','')[:60]}")
        key = (d.get("pagination") or {}).get("next_key")
        if not key:
            break
except Exception as e:
    print("regen:", e)

# ---------- 3e. Hypercerts (55k claims — grab a 2k slice, dedup by org-ish name) ----------
try:
    for off in range(0, 2000, 200):
        req = urllib.request.Request(
            "https://api.hypercerts.org/v1/graphql",
            data=json.dumps({"query": '{ hypercerts(first: 200, offset: %d) { data { hypercert_id metadata { name description } } } }' % off}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "defi4refi-leads/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        for h in d["data"]["hypercerts"]["data"]:
            md = h.get("metadata") or {}
            if md.get("name"):
                add(md["name"], "hypercerts", category="impact cert minter",
                    website="https://app.hypercerts.org/hypercerts/" + h["hypercert_id"],
                    notes=(md.get("description") or "")[:200])
        time.sleep(0.5)
except Exception as e:
    print("hypercerts:", e)

# ---------- 3f. Climate Week NYC event hosts (scraped listing page) ----------
try:
    h = open("/tmp/cwnyc.html").read()
    for attrs, body in re.findall(r'<article class="event-card ([^"]*)"(.*?)>(.*?)</article>', h, re.S):
        name = re.search(r'data-name="([^"]+)"', body)
        summ = re.search(r'data-summary="([^"]*)"', body)
        themes = " ".join(sorted(set(re.findall(r'theme-(\w+)', attrs))))
        add((name.group(1) if name else "?").replace("&amp;", "&"),
            "climateweek-nyc", category="climate event host (2026)",
            website="https://www.climateweeknyc.org/event-search",
            notes=((summ.group(1) if summ else "")[:200] + f" [themes: {themes}]"))
except Exception as e:
    print("climateweek:", e)

# ---------- 3g. UN Global Compact participants (env-relevant sectors slice) ----------
UNGC_SECTORS = re.compile(r"renewable|environment|energy|forestr|agricultur|conservation|recycl|water|solar|wind|carbon|climate|software|nature|sustainab|non-?profit|foundation", re.I)
try:
    for page in range(1, 31):
        req = urllib.request.Request(
            f"https://unglobalcompact.org/what-is-gc/participants/search?page={page}",
            headers={"User-Agent": "Mozilla/5.0"})
        h = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
            nm = re.search(r"notranslate name'><a href=\"([^\"]+)\">([^<]+)</a>", row)
            sector = re.search(r"class='sector'>([^<]*)<", row)
            country = re.search(r"class='country'>([^<]*)<", row)
            if nm and sector and UNGC_SECTORS.search(sector.group(1)):
                add(nm.group(2).strip(), "un-global-compact",
                    category=f"UNGC member ({sector.group(1).strip()})",
                    website="https://unglobalcompact.org" + nm.group(1),
                    notes=f"sector {sector.group(1).strip()}, {country.group(1).strip() if country else ''}")
        time.sleep(0.5)
except Exception as e:
    print("ungc:", e)

# ---------- 4. User's 19-token list ----------
for name, site, chain in [
    ("VeBetterDAO", "https://vebetter.com/", "Vechain"), ("Klima Protocol (kVCM)", "https://www.klimaprotocol.com/", "Base"),
    ("Powerledger (POWR)", "https://www.powerledger.io/", "Ethereum+Solana"), ("Energy Web (EWT)", "https://www.energyweb.org/", "Ethereum"),
    ("Dimitra (DMTR)", "https://dimitra.io/", "Ethereum"), ("DOVU", "https://dovu.earth/", "Hedera+Base"),
    ("My Lovely Planet", "https://www.mylovelyplanet.org/", "Polygon"), ("Regen Network", "https://www.regen.network/", "Osmosis+EVM"),
    ("IMPT", "https://www.impt.io/", "Ethereum"), ("LandX", "https://landx.fi/", "Ethereum"),
    ("SolarCoin", "https://solarcoin.org/", "Base+Ethereum"), ("Treegens", "https://treegens.app/", "Base"),
    ("Helios (HLSP)", "https://helios.eco/", "Base"), ("Unergy", "https://suno.finance/", "Polygon"),
    ("Kula", "https://www.kula.com/", "Avalanche"), ("Lake (LAK3)", "https://lak3.io/", "Ethereum"),
    ("Glow", "https://app.glow.org/", "Ethereum"), ("SAN", "https://www.goodbyemonkey.com/", "Solana"),
    ("Crypto Endowment Network (CEN)", "https://cryptoendowmentnetwork.org/", "Base"),
]:
    add(name, "user-token-list", category="impact token (two-token/Ohm-fork candidate)", website=site, chain=chain)

# ---------- 5. Curated ReFi / public-goods orgs ----------
for name, site, cat, notes in [
    ("Toucan Protocol", "https://toucan.earth/", "carbon infra", "TCO2 bridge; 60+ integrators"),
    ("KlimaDAO", "https://www.klimadao.finance/", "carbon infra", "K2/kVCM ecosystem"),
    ("Solid World", "https://www.solid.world/", "carbon infra", "carbon forward liquidity"),
    ("Thallo", "https://www.thallo.io/", "carbon infra", "carbon exchange"),
    ("Neutral", "https://www.neutralx.com/", "carbon infra", "tokenized environmental assets"),
    ("Open Forest Protocol", "https://www.openforestprotocol.org/", "ecological verification", "forestry project registry"),
    ("GainForest", "https://gainforest.earth/", "ecological verification", "AI+web3 rainforest"),
    ("dClimate", "https://www.dclimate.net/", "climate data", "parametric insurance data"),
    ("Astral", "https://astral.global/", "location protocols", "geospatial proofs"),
    ("Silvi", "https://www.silvi.earth/", "reforestation", "tree-planting verification + bioregional grants"),
    ("Kokonut Network", "https://kokonut.network/", "regen agriculture", "coconut farms RWA, Arbitrum"),
    ("Grassroots Economics / Sarafu", "https://www.grassrootseconomics.org/", "community currency", "commitment pooling, Kenyan CICs"),
    ("Breadchain Cooperative", "https://breadchain.xyz/", "community currency", "BREAD token, solidarity economy"),
    ("Impact Market", "https://impactmarket.com/", "UBI communities", "Celo UBI"),
    ("GoodDollar", "https://www.gooddollar.org/", "UBI", "G$ universal basic income"),
    ("ReFi DAO", "https://refidao.com/", "ecosystem", "30+ local nodes — partner + distribution"),
    ("GreenPill Network", "https://greenpill.network/", "ecosystem", "chapters + Dev Guild"),
    ("Bloom Network", "https://bloomnetwork.earth/", "ecosystem", "local regen communities"),
    ("Open Civics", "https://opencivics.co/", "ecosystem", "civic innovation network"),
    ("BioFi Project", "https://biofi.earth/", "ecosystem", "bioregional finance"),
    ("Let's Grow DAO", "https://letsgrow.network/", "ecosystem", "HATS/governance"),
    ("1Hive / Gardens", "https://gardens.fund/", "governance tooling", "conviction funding platform"),
    ("Gitcoin", "https://www.gitcoin.co/", "public goods infra", "Allo protocol"),
    ("Giveth", "https://giveth.io/", "public goods infra", "donation platform"),
    ("Octant", "https://octant.build/", "public goods infra", "epoch funding, GLM staking"),
    ("Drips", "https://www.drips.network/", "public goods infra", "FOSS funding streams"),
    ("Hypercerts", "https://hypercerts.org/", "impact certs", "impact attestation primitive"),
    ("Karma (GAP)", "https://www.karmahq.xyz/", "accountability", "grantee profiles — also a data source"),
    ("Ma Earth", "https://maearth.com/", "grantmaker", "land/ocean regen QF rounds"),
    ("Celo Public Goods", "https://celopg.eco/", "ecosystem funder", "Prezenti, CeloPG rounds"),
    ("Glo Dollar", "https://glodollar.org/", "impact stablecoin", "yield-funded public goods"),
    ("Optimism Collective", "https://gov.optimism.io/", "ecosystem funder", "Retro Funding missions"),
    ("Filecoin Foundation / FIL-PGF", "https://filpgf.io/", "ecosystem funder", "ProPGF batches + devgrants"),
    ("Ethereum Foundation ESP", "https://esp.ethereum.foundation/", "ecosystem funder", "ecosystem support program"),
    ("Funding the Commons", "https://fundingthecommons.io/", "ecosystem", "events + community"),
    ("Greenpill Dev Guild", "https://greenpill.network/", "peer/competitor", "grant-funded dev capacity"),
    ("splitlabs", "https://splitlabs.io/", "peer/competitor", "AI+Solana studio"),
    ("OnlyDust", "https://www.onlydust.com/", "contributor funding", "OSS bounty platform"),
    ("M3tering", "https://m3tering.ing/", "protocol", "energy settlement — underfunded, free-tier candidate"),
    ("Pasanaku", "", "protocol", "trustless ROSCA — Artizen S7"),
    ("Regen Coordination", "", "ecosystem", "ReFi DAO+GreenPill+Bloom alliance — Artizen S7"),
]:
    add(name, "curated", category=cat, website=site, notes=notes)

# ---------- dedupe & write ----------
seen, out = set(), []
for l in leads:
    key = l["name"].lower()
    if key not in seen:
        seen.add(key); out.append(l)

import os
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)
print(f"wrote {len(out)} leads → {OUT}")
from collections import Counter
print(Counter(l["source"] for l in out))
