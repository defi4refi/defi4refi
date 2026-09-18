#!/usr/bin/env python3
"""Load additional keyless sources into defi4refi.raw_leads (ClickHouse)."""
import json, re, time, urllib.request, urllib.parse

CH = "http://localhost:8123/"

def insert(rows):
    if not rows:
        return
    body = "\n".join(json.dumps(r) for r in rows)
    q = urllib.parse.quote(
        "INSERT INTO defi4refi.raw_leads (source,name,category,raised_usd,website,chain,notes,priority) FORMAT JSONEachRow")
    urllib.request.urlopen(urllib.request.Request(CH + "?query=" + q, data=body.encode()))

def row(source, name, category="", raised=0.0, website="", chain="", notes="", priority=""):
    return {"source": source, "name": name, "category": category, "raised_usd": float(raised),
            "website": website, "chain": chain, "notes": notes[:900], "priority": priority}

def get(url, data=None, ua="defi4refi-leads/1.0"):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": ua})
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")

# --- GitHub extra topics ---
for topic in ["community-currency", "impact", "climate", "climate-change", "dao-tooling",
              "impact-market", "tokenized-carbon", "biodiversity"]:
    try:
        d = json.loads(get(f"https://api.github.com/search/repositories?q=topic:{topic}&per_page=30&sort=stars"))
        insert([row("github-topic-" + topic, r["full_name"], "oss repo", r.get("stargazers_count") or 0,
                    r["html_url"], notes=(r.get("description") or "")[:300])
                for r in d.get("items", [])])
        print("github", topic, len(d.get("items", [])))
        time.sleep(1)
    except Exception as e:
        print("github", topic, "ERR", e)

# --- Celo forum: ecosystem category + search for grant posts ---
try:
    for page in range(0, 5):
        d = json.loads(get(f"https://forum.celo.org/c/ecosystem/25.json?page={page}", ua="Mozilla/5.0"))
        topics = (d.get("topic_list") or {}).get("topics") or []
        if not topics:
            break
        insert([row("celo-forum", t["title"], "celo ecosystem project", website=f"https://forum.celo.org/t/{t['slug']}/{t['id']}",
                    notes=f"posts:{t.get('posts_count')} views:{t.get('views')} activity:{t.get('last_posted_at','')[:10]}")
                for t in topics])
        print("celo-forum page", page, len(topics))
        time.sleep(0.5)
except Exception as e:
    print("celo forum ERR", e)

# --- DexScreener latest token profiles + boosted (filter env/refi keywords) ---
KW = re.compile(r"regen|refi|carbon|climat|eco|environ|forest|tree|solar|energy|green|sustain|biodiv|ocean|water|agro|farm|impact|nature|planet|earth|reef|wildlife", re.I)
for ep, tag in [("https://api.dexscreener.com/token-profiles/latest/v1", "dexscreener-profiles"),
                ("https://api.dexscreener.com/token-boosts/latest/v1", "dexscreener-boosted"),
                ("https://api.dexscreener.com/token-boosts/top/v1", "dexscreener-boosted-top")]:
    try:
        d = json.loads(get(ep))
        hits = []
        for t in d:
            text = " ".join(str(t.get(k) or "") for k in ("name", "description", "header"))
            if KW.search(text):
                hits.append(row(tag, t.get("header") or t.get("tokenAddress", "?"), "impact token (dexscreener)",
                                website=t.get("url", ""), chain=t.get("chainId", ""),
                                notes=(t.get("description") or "")[:300]))
        insert(hits)
        print(tag, len(d), "→", len(hits), "env hits")
    except Exception as e:
        print(tag, "ERR", e)

# --- UN Global Compact: continue deeper pagination for env sectors ---
UNGC_SECTORS = re.compile(r"renewable|environment|energy|forestr|agricultur|conservation|recycl|water|solar|wind|carbon|climate|nature|sustainab|non-?profit|foundation|ngo", re.I)
try:
    for page in range(61, 161):
        h = get(f"https://unglobalcompact.org/what-is-gc/participants/search?page={page}", ua="Mozilla/5.0")
        n = 0
        for r in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
            nm = re.search(r"notranslate name'><a href=\"([^\"]+)\">([^<]+)</a>", r)
            sector = re.search(r"class='sector'>([^<]*)<", r)
            country = re.search(r"class='country'>([^<]*)<", r)
            if nm and sector and UNGC_SECTORS.search(sector.group(1)):
                insert([row("un-global-compact", nm.group(2).strip(),
                            f"UNGC member ({sector.group(1).strip()})",
                            website="https://unglobalcompact.org" + nm.group(1),
                            notes=f"sector {sector.group(1).strip()}, {country.group(1).strip() if country else ''}")])
                n += 1
        time.sleep(0.3)
except Exception as e:
    print("ungc ERR", e)

print("done")
