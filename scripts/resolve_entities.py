#!/usr/bin/env python3
"""Entity resolution: raw_leads -> orgs (union-find on domain/github/twitter + fuzzy name merge)."""
import json, re, urllib.parse, urllib.request
from urllib.parse import quote
from rapidfuzz import fuzz

CH = "http://localhost:8123/"

def q(sql, data=None):
    url = CH + "?query=" + quote(sql)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=(data.encode() if data else b""), method="POST"))
        return r.read().decode()
    except Exception as e:
        print("QUERY FAILED:", sql[:200])
        body = getattr(e, "read", lambda: b"")()
        print("CH says:", body[:300] if body else e)
        raise

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def norm_domain(url):
    if not url:
        return ""
    try:
        d = urllib.parse.urlparse(url if "//" in url else "https://" + url).netloc.lower()
        d = d.split("@")[-1].split(":")[0]
        return re.sub(r"^www\.", "", d)
    except Exception:
        return ""

def norm_handle(h):
    return (h or "").strip().lstrip("@").lower()

def gh_org(u):
    m = re.search(r"github\.com/([^/\s?#]+)", u or "")
    return (m.group(1).lower() if m else "")

def tw_handle(u):
    m = re.search(r"(?:twitter\.com|x\.com)/([^/\s?#]+)", u or "")
    return (m.group(1).lower() if m else "")

# ---- load raw rows ----
rows = rows_json("SELECT source,name,website,chain,notes,priority FROM defi4refi.raw_leads")
print("raw rows:", len(rows))

# ---- extract join keys ----
PLATFORMS = ("github.com", "twitter.com", "x.com", "giveth.io", "artizen.fyi", "forum.celo.org",
             "hypercerts.org", "app.hypercerts.org", "coingecko.com", "unglobalcompact.org",
             "climateweeknyc.org", "dexscreener.com", "0gent.xyz", "0x01.world", "linktr.ee", "linktree.com",
             "medium.com", "substack.com", "youtube.com", "docs.google.com", "notion.site",
             "vercel.app", "netlify.app", "pages.dev", "webflow.io", "zcashgrants.org",
             "grants-admin.zfnd.org", "twitter.com", "discord.gg", "t.me", "t.co", "bit.ly",
             "0xblockbard.com", "hypercert.social", "link3.to", "beacons.ai", "campsite.bio")

SHARED_GH = {"zcashcommunitygrants", "gitcoinco", "giveth"}  # program/host orgs, not projects

def keys_of(r):
    keys = []
    dom = norm_domain(r["website"])
    if dom and "." in dom and not dom.endswith(PLATFORMS):
        keys.append(("dom", dom))
    else:
        dom = ""  # platform domains are not org identity
    gh = gh_org(r["website"]) or gh_org(r["notes"])
    if gh and gh not in ("orgs", "topics", "search") and gh not in SHARED_GH:
        keys.append(("gh", gh))
    tw = tw_handle(r["website"]) or tw_handle(r["notes"])
    if tw:
        keys.append(("tw", tw))
    m = re.search(r"tw:([A-Za-z0-9_]+)", r["notes"] or "")
    if m:
        keys.append(("tw", norm_handle(m.group(1))))
    return keys, dom, gh, tw

# ---- union-find ----
parent = list(range(len(rows)))
def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra

key_idx = {}
meta = []
row_keys = []
for i, r in enumerate(rows):
    ks, dom, gh, tw = keys_of(r)
    meta.append((dom, gh, tw))
    row_keys.append(ks)

# drop platform/shared keys used by >50 rows (whack-a-mole guard)
from collections import Counter
key_freq = Counter(k for ks in row_keys for k in ks)
for i, ks in enumerate(row_keys):
    for k in ks:
        if key_freq[k] > 50:
            continue
        if k in key_idx:
            union(i, key_idx[k])
        else:
            key_idx[k] = i
dropped = [k for k, c in key_freq.items() if c > 50]
print("shared-key drops:", dropped[:10], f"({len(dropped)} keys)")

clusters = {}
for i in range(len(rows)):
    clusters.setdefault(find(i), []).append(i)
print("clusters:", len(clusters), " multi-source:", sum(1 for c in clusters.values() if len(c) > 1))

# ---- fuzzy name merge pass (org names across sources) ----
# canonical name per cluster = shortest non-repo name
def canon(idxs):
    cands = sorted({rows[i]["name"].strip() for i in idxs}, key=len)
    return cands[0] if cands else "?"

import hashlib
def mk_oid(doms, ghs, idxs):
    dom = sorted(doms)[0] if doms else ""
    if dom:
        return dom
    if ghs:
        return sorted(ghs)[0]
    # deterministic fallback: stable across rebuilds (unlike union-find root)
    return "n-" + hashlib.md5(re.sub(r"[^a-z0-9]", "", canon(idxs).lower()).encode()).hexdigest()[:14]

names = [(root, canon(idxs)) for root, idxs in clusters.items()]
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
name_idx = {}
merges = 0
for a in range(len(names)):
    na = norm(names[a][1])
    if len(na) < 5:
        continue
    if na in name_idx:
        union(names[a][0], name_idx[na]); merges += 1
    else:
        name_idx[na] = names[a][0]
print("exact-norm name merges:", merges)

# fuzzy: compare names sharing first 6 chars bucket (bounded)
buckets = {}
for root, nm in names:
    b = norm(nm)[:6]
    if len(b) >= 6:
        buckets.setdefault(b, []).append((root, nm))
for b, lst in buckets.items():
    uniq = list({norm(nm): (root, nm) for root, nm in lst}.values())
    if len(uniq) > 300:
        continue
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            if fuzz.ratio(norm(uniq[i][1]), norm(uniq[j][1])) > 92:
                union(uniq[i][0], uniq[j][0])

# ---- rebuild clusters post-merge, emit orgs ----
clusters = {}
for i in range(len(rows)):
    clusters.setdefault(find(i), []).append(i)

orgs = []
for root, idxs in clusters.items():
    doms = {meta[i][0] for i in idxs if ("dom", meta[i][0]) in key_freq and key_freq[("dom", meta[i][0])] <= 50} - {""}
    ghs = {meta[i][1] for i in idxs} - {""}
    tws = {meta[i][2] for i in idxs} - {""}
    srcs = sorted({rows[i]["source"] for i in idxs})
    chains = ",".join(sorted({rows[i]["chain"] for i in idxs} - {""}))
    dom = sorted(doms)[0] if doms else ""
    org_id = mk_oid(doms, ghs, idxs)
    orgs.append({"org_id": org_id, "canonical_name": canon(idxs), "domain": dom,
                 "github": ",".join(sorted(ghs)), "twitter": ",".join(sorted(tws)),
                 "farcaster": "", "ens": "", "chains": chains,
                 "source_count": len(srcs), "sources": ",".join(srcs)})

body = "\n".join(json.dumps(o) for o in orgs)
q("INSERT INTO defi4refi.orgs FORMAT JSONEachRow", data=body)
print("orgs written:", len(orgs))

# ---- write org_id back to raw_leads ----
# clickhouse: use ALTER UPDATE per org (few hundred multi-row orgs; do by name join instead)
q("""ALTER TABLE defi4refi.raw_leads UPDATE org_id =
  (SELECT org_id FROM defi4refi.orgs o WHERE
    (o.domain != '' AND o.domain = lower(extractURLParameter(concat('//', r.website), '')) ) LIMIT 1)
  FROM defi4refi.raw_leads r WHERE 1 SETTINGS mutations_sync=0""") if False else None
# simpler: per-org update by name match is unreliable; store mapping in a join table instead
q("""CREATE TABLE IF NOT EXISTS defi4refi.lead_org_map (
     name String, source String, org_id String
   ) ENGINE = MergeTree ORDER BY org_id""")

mrows = []
for root, idxs in clusters.items():
    doms = {meta[i][0] for i in idxs if ("dom", meta[i][0]) in key_freq and key_freq[("dom", meta[i][0])] <= 50} - {""}
    ghs = {meta[i][1] for i in idxs} - {""}
    dom = sorted(doms)[0] if doms else ""
    org_id = mk_oid(doms, ghs, idxs)
    for i in idxs:
        mrows.append({"name": rows[i]["name"], "source": rows[i]["source"], "org_id": org_id})
body = "\n".join(json.dumps(m) for m in mrows)
q("INSERT INTO defi4refi.lead_org_map FORMAT JSONEachRow", data=body)
print("lead_org_map rows:", len(mrows))

# ---- funding events from karma jsonl ----
import os
KARMA = "/home/terex/CascadeProjects/defi4refi/data/karma_projects.jsonl"
name2org = {}
for root, idxs in clusters.items():
    doms = {meta[i][0] for i in idxs if ("dom", meta[i][0]) in key_freq and key_freq[("dom", meta[i][0])] <= 50} - {""}
    ghs = {meta[i][1] for i in idxs} - {""}
    dom = sorted(doms)[0] if doms else ""
    oid = mk_oid(doms, ghs, idxs)
    for i in idxs:
        name2org[rows[i]["name"].lower()] = oid

evs = []
if os.path.exists(KARMA):
    for line in open(KARMA):
        try:
            p = json.loads(line)
        except Exception:
            continue
        det = (p.get("details") or {}).get("data") or {}
        title = (det.get("title") or "").lower()
        oid = name2org.get(title)
        if not oid:
            continue
        dt = (p.get("createdAt") or "")[:10] or "1970-01-01"
        evs.append({"org_id": oid, "source": "karma-gap", "program": "project-profile",
                    "amount_usd": 0, "event_date": dt,
                    "evidence": "gap.karmahq.xyz/" + (det.get("slug") or "")})
        for g in (p.get("grants") or []):
            gd = (g.get("details") or {}).get("data") or {}
            evs.append({"org_id": oid, "source": "karma-gap",
                        "program": gd.get("title") or (g.get("details") or {}).get("slug", "grant"),
                        "amount_usd": float(g.get("amount") or 0) if str(g.get("amount") or "").replace(".", "").isdigit() else 0,
                        "event_date": (g.get("createdAt") or dt)[:10],
                        "evidence": ""})
if evs:
    body = "\n".join(json.dumps(e) for e in evs)
    q("INSERT INTO defi4refi.funding_events FORMAT JSONEachRow", data=body)
print("funding_events:", len(evs))
print("DONE")
