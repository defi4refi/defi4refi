#!/usr/bin/env python3
"""Rebuild funding_events with real $ amounts: karma grants+raisedMoney, giveth
totalDonations, hypercert sales, coingecko mcap, artizen rank estimate."""
import json, re, time, urllib.request, urllib.parse

CH = "http://localhost:8123/"

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def rows_json(sql):
    return [json.loads(l) for l in q(sql + " FORMAT JSONEachRow").strip().splitlines() if l.strip()]

def emit(evs):
    if evs:
        q("INSERT INTO defi4refi.funding_events FORMAT JSONEachRow", data="\n".join(json.dumps(e) for e in evs))

q("TRUNCATE TABLE defi4refi.funding_events")
evs = []

# name -> org_id
name2org = {r["name"].lower(): r["org_id"] for r in rows_json("SELECT name, org_id FROM defi4refi.lead_org_map")}
hc2org = {}  # hypercert_id -> org
for r in rows_json("SELECT name, org_id, website FROM defi4refi.lead_org_map m JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source WHERE m.source='hypercerts'"):
    m = re.search(r"hypercerts/(.+)$", r["website"])
    if m:
        hc2org[m.group(1)] = r["org_id"]

# ---- karma: grant rows + self-reported raisedMoney ----
def parse_money(text):
    if not text:
        return 0.0
    t = str(text)
    if re.search(r"(?i)\$?0\b|none|bootstrapp|self.?fund|no fund|start ?up|n/a", t) and not re.search(r"[\d,]{4,}", t):
        return 0.0
    nums = [float(n.replace(",", "")) for n in re.findall(r"([\d][\d,]{2,}(?:\.\d+)?)", t)]
    nums = [n for n in nums if 500 <= n <= 50_000_000]
    return max(nums) if nums else 0.0

for line in open("data/karma_projects.jsonl"):
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
                "amount_usd": 0, "event_date": dt, "evidence": ""})
    raised = parse_money(det.get("raisedMoney"))
    if raised:
        evs.append({"org_id": oid, "source": "karma-gap", "program": "self-reported-raised",
                    "amount_usd": raised, "event_date": dt, "evidence": (det.get("raisedMoney") or "")[:120]})
    for g in (p.get("grants") or []):
        gd = (g.get("details") or {}).get("data") or {}
        amt = g.get("amount") or gd.get("amount") or 0
        try:
            amt = float(amt)
        except Exception:
            amt = 0.0
        evs.append({"org_id": oid, "source": "karma-gap",
                    "program": gd.get("title") or "grant", "amount_usd": amt,
                    "event_date": (g.get("createdAt") or dt)[:10] or "1970-01-01",
                    "evidence": (g.get("proposalURL") or "")[:200]})
print("karma events:", len(evs))

# ---- giveth totalDonations ----
for r in rows_json("SELECT name, org_id, raised_usd FROM defi4refi.lead_org_map m JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source WHERE m.source='giveth' AND l.raised_usd > 0"):
    evs.append({"org_id": r["org_id"], "source": "giveth", "program": "giveth-donations",
                "amount_usd": r["raised_usd"], "event_date": "1970-01-01",
                "evidence": "giveth totalDonations"})
print("+giveth:", len(evs))

# ---- hypercerts sales -> usd (stable decimals map) ----
DEC18 = {"0x471ece3750da237f93b8e339c536989b8978a438"}  # cUSD
try:
    for off in range(0, 5000, 200):
        req = urllib.request.Request("https://api.hypercerts.org/v1/graphql",
            data=json.dumps({"query": '{ sales(first:200, offset:%d) { data { hypercert_id amounts currency creation_block_timestamp } } }' % off}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "defi4refi/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        sales = d["data"]["sales"]["data"]
        if not sales:
            break
        for s in sales:
            oid = hc2org.get(s["hypercert_id"])
            if not oid:
                continue
            cur = (s.get("currency") or "").lower()
            dec = 18 if cur in DEC18 else 6
            usd = sum(float(a) for a in (s.get("amounts") or [])) / 10**dec
            if 1 <= usd <= 10_000_000:
                evs.append({"org_id": oid, "source": "hypercerts", "program": "hypercert-sale",
                            "amount_usd": round(usd, 2),
                            "event_date": time.strftime("%Y-%m-%d", time.gmtime(int(s.get("creation_block_timestamp") or 0))),
                            "evidence": s["hypercert_id"][:40]})
        time.sleep(0.3)
except Exception as e:
    print("hypercert sales:", e)
print("+hypercerts:", len(evs))

# ---- coingecko mcap (treasury proxy) ----
for r in rows_json("SELECT name, org_id, raised_usd FROM defi4refi.lead_org_map m JOIN defi4refi.raw_leads l ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source WHERE m.source='coingecko-eco' AND l.raised_usd > 0"):
    evs.append({"org_id": r["org_id"], "source": "coingecko", "program": "token-market-cap",
                "amount_usd": r["raised_usd"], "event_date": "1970-01-01", "evidence": ""})
print("+coingecko:", len(evs))

# ---- generic promotion: any raw_leads.raised_usd>0 not covered above ----
for r in rows_json("""
  SELECT m.org_id AS org_id, l.name AS name, l.source AS source, max(l.raised_usd) AS amt
  FROM defi4refi.lead_org_map m JOIN defi4refi.raw_leads l
    ON trim(splitByString('│', l.name)[1])=m.name AND l.source=m.source
  WHERE l.raised_usd > 0 AND l.source NOT IN ('giveth','coingecko-eco')
  GROUP BY org_id, name, source"""):
    evs.append({"org_id": r["org_id"], "source": r["source"], "program": "reported-amount",
                "amount_usd": r["amt"], "event_date": "1970-01-01", "evidence": "raw_leads.raised_usd"})

emit(evs)
print("total funding_events:", len(evs))
