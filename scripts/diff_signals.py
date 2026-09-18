#!/usr/bin/env python3
"""Freshness triggers v2: multi-source weekly diff -> signals. Run via cron."""
import json, os, time, urllib.request, urllib.parse

CH = "http://localhost:8123/"
WM_DIR = "/home/terex/CascadeProjects/defi4refi/data"
os.makedirs(WM_DIR, exist_ok=True)

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def get(url, data=None, hdrs=None):
    req = urllib.request.Request(url, data=data,
        headers={"User-Agent": "defi4refi-leads/1.0", **(hdrs or {})})
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")

def watermark(name, default="1970-01-01"):
    p = f"{WM_DIR}/.wm_{name}"
    try:
        return open(p).read().strip()
    except FileNotFoundError:
        return default

def set_watermark(name, v):
    open(f"{WM_DIR}/.wm_{name}", "w").write(v)

signals = []

# --- 1. Karma GAP: new attestations + grants ---
wm = watermark("karma")
new_wm = wm
title2org = {r["name"].lower(): r["org_id"] for r in
             rows_json("SELECT name, org_id FROM defi4refi.lead_org_map WHERE source='karma-gap'")}
stop = False
for page in range(1, 60):
    if stop: break
    try:
        d = json.loads(get(f"https://gapapi.karmahq.xyz/projects?page={page}"))
    except Exception:
        break
    if not d: break
    for p in d:
        ca = p.get("createdAt", "")
        if ca and ca[:10] <= wm:
            stop = True; break
        if ca > new_wm: new_wm = ca
        title = ((p.get("details") or {}).get("data") or {}).get("title") or ""
        oid = title2org.get(title.lower())
        for g in (p.get("grants") or []):
            signals.append({"org_id": oid or "?" + title[:40], "signal_type": "new_grant",
                "detail": f"grant via Karma, created {ca[:10]}: {((g.get('details') or {}).get('data') or {}).get('title','')[:60]}"})
        if oid is None and title:
            signals.append({"org_id": "?" + title[:40], "signal_type": "new_project",
                "detail": f"new karma profile {ca[:10]}"})
    time.sleep(0.25)
set_watermark("karma", new_wm)
print("karma: wm", wm, "->", new_wm, "| signals so far:", len(signals))

# --- 2. Giveth: new projects (creationDate watermark) ---
wm = watermark("giveth")
new_wm = wm
try:
    d = json.loads(get("https://mainnet.serve.giveth.io/graphql",
        data=json.dumps({"query": '{ allProjects(limit:50, sortingBy:Newest) { projects { title slug creationDate } } }'}).encode(),
        hdrs={"Content-Type": "application/json", "authVersion": "2"}))
    for p in d["data"]["allProjects"]["projects"]:
        cd = (p.get("creationDate") or "")[:10]
        if cd <= wm: continue
        if cd > new_wm: new_wm = cd
        signals.append({"org_id": "giveth:" + p["slug"], "signal_type": "new_project",
                        "detail": f"new Giveth project {p['title'][:60]} created {cd}"})
    set_watermark("giveth", new_wm)
    print("giveth new:", new_wm)
except Exception as e:
    print("giveth:", e)

# --- 3. Hypercerts: new claims (count watermark) ---
wm = watermark("hypercerts", "0")
try:
    d = json.loads(get("https://api.hypercerts.org/v1/graphql",
        data=json.dumps({"query": "{ hypercerts(first: 1) { count } }"}).encode(),
        hdrs={"Content-Type": "application/json"}))
    total = int(d["data"]["hypercerts"]["count"])
    if total > int(wm):
        signals.append({"org_id": "", "signal_type": "hypercert_volume",
                        "detail": f"hypercerts {wm} -> {total} (+{total-int(wm)} new)"})
    set_watermark("hypercerts", str(total))
    print("hypercerts:", wm, "->", total)
except Exception as e:
    print("hypercerts:", e)

# --- 4. CoinGecko eco category: new listings ---
wm = watermark("coingecko")
try:
    d = json.loads(get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=eco-friendly&order=market_cap_desc&per_page=50"))
    cur = {c["id"] for c in d}
    prev = set(json.loads(wm)) if wm != "1970-01-01" else set()
    for c in d:
        if c["id"] not in prev:
            signals.append({"org_id": "", "signal_type": "new_eco_token",
                "detail": f"new eco listing: {c['name']} ({c['symbol']}) mcap {c.get('market_cap')}"})
    set_watermark("coingecko", json.dumps(sorted(cur)))
    print("coingecko tracked:", len(cur), "prev:", len(prev))
except Exception as e:
    print("coingecko:", e)

if signals:
    q("INSERT INTO defi4refi.signals FORMAT JSONEachRow", data="\n".join(json.dumps(s) for s in signals))
print(f"TOTAL signals: {len(signals)}")
for s in signals[:10]:
    print(" ", s["signal_type"], "|", s["detail"][:80])
