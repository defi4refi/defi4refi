#!/usr/bin/env python3
"""Scale loaders: USASpending recipients, OpenCollective all, Giveth all, ProPublica broad."""
import json, time, urllib.request, urllib.parse

CH = "http://localhost:8123/"

def q(sql, data=None):
    r = urllib.request.urlopen(urllib.request.Request(
        CH + "?query=" + urllib.parse.quote(sql), data=(data.encode() if data else b""), method="POST"))
    return r.read().decode()

def insert(rows):
    if rows:
        q("INSERT INTO defi4refi.raw_leads (source,name,category,raised_usd,website,chain,notes,priority) FORMAT JSONEachRow",
          data="\n".join(json.dumps(r) for r in rows))

def row(source, name, category="", raised=0.0, website="", chain="", notes="", priority=""):
    return {"source": source, "name": name, "category": category, "raised_usd": float(raised or 0),
            "website": website, "chain": chain, "notes": notes[:900], "priority": priority}

def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data,
        headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")

# ---------- USASpending: env-agency grant recipients ----------
def usaspending():
    # agencies: EPA, DOE, USDA, NOAA(Commerce), NSF, USAID, Interior
    agencies = {"epa":"Environmental Protection Agency","doe":"Department of Energy",
                "usda":"Department of Agriculture","noaa":"Department of Commerce",
                "nsf":"National Science Foundation","usaid":"Agency for International Development",
                "doi":"Department of the Interior","dot":"Department of Transportation",
                "hud":"Department of Housing and Urban Development"}
    total = 0
    for code, agency in agencies.items():
        page, done = 1, False
        while not done and page <= 60:
            body = {"filters": {"time_period": [{"start_date": "2020-01-01", "end_date": "2026-12-31"}],
                                "award_type_codes": ["02","03","04","05"],
                                "agencies": [{"type": "awarding", "tier": "toptier", "name": agency}]},
                    "fields": ["Recipient Name", "Award Amount", "Start Date", "Awarding Agency"],
                    "limit": 100, "page": page, "sort": "Award Amount", "order": "desc"}
            try:
                d = json.loads(get("https://api.usaspending.gov/api/v2/search/spending_by_award/",
                                   data=json.dumps(body).encode()))
            except Exception as e:
                print("usaspending", agency, "page", page, e); break
            res = d.get("results") or []
            rows = [row("usaspending", r["Recipient Name"].strip("` ").title(),
                        f"US federal grant ({agency})", raised=r.get("Award Amount") or 0,
                        website=f"https://www.usaspending.gov/award/{r.get('generated_internal_id','')}",
                        notes=f"{agency} award ${r.get('Award Amount',0):,.0f} start:{(r.get('Start Date') or '')[:10]}")
                    for r in res if r.get("Recipient Name")]
            insert(rows)
            total += len(rows)
            done = not (d.get("page_metadata") or {}).get("hasNext")
            page += 1
            time.sleep(0.4)
        print("usaspending", agency, "done")
    print("usaspending total:", total)

# ---------- Open Collective: ALL collectives w/ budgets ----------
def opencollective_all():
    out, off = [], 0
    qg = '{ accounts(limit:100, offset:%d, type:[COLLECTIVE]) { nodes { name slug website stats { totalNetAmountReceived { value currency } } tags } } }'
    while off < 20000:
        try:
            d = json.loads(get("https://api.opencollective.com/graphql/v2",
                data=json.dumps({"query": qg % off}).encode(),
                headers={"Content-Type": "application/json"}))
            nodes = d["data"]["accounts"]["nodes"]
            if not nodes: break
            for a in nodes:
                rec = ((a.get("stats") or {}).get("totalNetAmountReceived") or {}).get("value") or 0
                out.append(row("opencollective", a["name"], "open collective",
                    raised=float(rec), website=a.get("website") or f"https://opencollective.com/{a['slug']}",
                    notes=f"raised ${rec:,.0f} tags:{','.join(a.get('tags') or [])}"))
            off += 100
            time.sleep(0.5)
        except Exception as e:
            print("oc", off, e); break
        if len(out) >= 4000:
            insert(out); out = []
    insert(out)
    print("opencollective done")

# ---------- Giveth: ALL projects unfiltered ----------
def giveth_all():
    out = []
    for skip in range(0, 3000, 50):
        try:
            d = json.loads(get("https://mainnet.serve.giveth.io/graphql",
                data=json.dumps({"query": '{ allProjects(limit:50, skip:%d, sortingBy:MostFunded) { projects { title slug totalDonations verified descriptionSummary } } }' % skip}).encode(),
                headers={"Content-Type": "application/json", "authVersion": "2"}))
            projs = d["data"]["allProjects"]["projects"]
            if not projs: break
            for p in projs:
                out.append(row("giveth-all", p["title"], "giveth project",
                    raised=round(p.get("totalDonations") or 0),
                    website="https://giveth.io/project/" + p["slug"],
                    notes=(p.get("descriptionSummary") or "")[:300]))
            time.sleep(0.4)
        except Exception as e:
            print("giveth", skip, e); break
        if len(out) >= 1000:
            insert(out); out = []
    insert(out); print("giveth-all done")

# ---------- ProPublica broad NTEE ----------
def propublica_broad():
    terms = ["climate", "conservation", "forest", "solar", "water", "sustainable",
             "renewable", "wildlife", "marine", "agriculture", "community development",
             "international development", "economic development"]
    out = []
    for term in terms:
        for page in range(0, 40):
            try:
                d = json.loads(get(f"https://projects.propublica.org/nonprofits/api/v2/search.json?q={urllib.parse.quote(term)}&page={page}"))
                for o in d.get("organizations", []):
                    rev = o.get("income_amount") or o.get("revenue_amount") or 0
                    out.append(row("propublica-990", o["name"], "US nonprofit (990)",
                        raised=rev, website=f"https://projects.propublica.org/nonprofits/organizations/{o['ein']}",
                        notes=f"EIN {o['ein']} {o.get('city','')},{o.get('state','')} NTEE:{o.get('ntee_code','')} income:${rev:,}"))
                if len(d.get("organizations", [])) < 25: break
                time.sleep(0.3)
            except Exception as e:
                print("pp", term, page, e); break
        if len(out) >= 3000:
            insert(out); out = []
    insert(out); print("propublica-broad done")

import sys
fns = {"usaspending": usaspending, "opencollective": opencollective_all,
       "giveth": giveth_all, "propublica": propublica_broad}
for a in (sys.argv[1:] or fns):
    fns[a]()
print("ALL DONE")
